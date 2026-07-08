"""
GraphExecutor — сборка, валидация и исполнение графа.

Алгоритм:
  1. По GraphSpec инстанцировать узлы через NodeRegistry.
  2. Построить карту входов: (узел, входной порт) → (узел-источник, выходной порт).
     При этом проверяется: узлы и порты существуют, типы совместимы, один вход
     не подключён дважды, нет циклов, заполнены все обязательные входы.
  3. Топологически отсортировать узлы.
  4. Исполнять в whole-graph retry: до meta.max_attempts раз прогонять весь граф;
     если узел бросает RetryGeneration — начать новую попытку (источники со
     случайностью пере-бросятся). Это аналог цикла в fisic_generater.generate_task.

Финал графа — единственный узел с выходом типа TASK, который никуда не подключён.
Внутри вложенных тел (repeat/map/ветви case) узлы с выходом TASK запрещены:
финал собирается только на верхнем уровне графа.
"""

from __future__ import annotations
import random
from typing import Any

from .errors import GraphError, GraphValidationError, RetryGeneration
from .node import ExecContext, Node
from .port_types import PortType, coerce_value, is_compatible
from .registry import NodeRegistry
from .spec import GraphSpec


# Тип ключа точки графа: (node_id, port_name)
Endpoint = tuple[str, str]


class GraphExecutor:
    def __init__(self, spec: GraphSpec, registry: NodeRegistry | None = None):
        from .nodes import DEFAULT_REGISTRY
        self.spec = spec
        self.registry = registry or DEFAULT_REGISTRY
        self.nodes: dict[str, Node] = {}
        self.in_edges: dict[Endpoint, Endpoint] = {}
        self.consumed: set[Endpoint] = set()
        self.order: list[str] = []
        self.result: Endpoint | None = None
        self._build()

    # ---------- Сборка и валидация ----------

    def _build(self) -> None:
        # 1. Узлы
        for ns in self.spec.nodes:
            if ns.id in self.nodes:
                raise GraphValidationError(f"Дублирующийся id узла: {ns.id!r}.")
            self.nodes[ns.id] = self.registry.create(ns.type, ns.id, ns.params)

        # Индексы портов по узлам — для проверки существования и типов.
        out_ports: dict[Endpoint, PortType] = {}
        in_ports: dict[Endpoint, PortType] = {}
        for node in self.nodes.values():
            for p in node.output_ports():
                out_ports[(node.node_id, p.name)] = p.type
            for p in node.input_ports():
                in_ports[(node.node_id, p.name)] = p.type

        # 2. Рёбра
        for e in self.spec.edges:
            src: Endpoint = (e.from_node, e.from_port)
            dst: Endpoint = (e.to_node, e.to_port)
            if src not in out_ports:
                raise GraphValidationError(
                    f"Провод ссылается на несуществующий выход {e.from_node}:{e.from_port}."
                )
            if dst not in in_ports:
                raise GraphValidationError(
                    f"Провод ссылается на несуществующий вход {e.to_node}:{e.to_port}."
                )
            if not is_compatible(out_ports[src], in_ports[dst]):
                raise GraphValidationError(
                    f"Несовместимые типы: {e.from_node}:{e.from_port} "
                    f"({out_ports[src].value}) → {e.to_node}:{e.to_port} "
                    f"({in_ports[dst].value})."
                )
            if dst in self.in_edges:
                raise GraphValidationError(
                    f"Вход {e.to_node}:{e.to_port} подключён более одного раза."
                )
            self.in_edges[dst] = src
            self.consumed.add(src)

        # 3. Обязательные входы заполнены?
        for node in self.nodes.values():
            for p in node.input_ports():
                if p.required and (node.node_id, p.name) not in self.in_edges:
                    raise GraphValidationError(
                        f"Не заполнен обязательный вход {node.node_id}:{p.name}."
                    )

        # Сохраняем типы выходов: нужны для поиска свободных типизированных
        # выходов (финал TASK, а также тело цикла — свободный BLOCK).
        self._out_port_types = out_ports

        # 4. Узлы-задания внутри вложенных тел (цикл/map/ветви case) запрещены:
        #    их TASK-выход там некому потребить — результат итерации передаётся
        #    свободным выходом BLOCK, а финал графа собирается на верхнем уровне.
        self._check_no_task_in_subgraphs()

        # 5. Структурные проверки узлов (согласованность с вложенными телами,
        #    например туннели вывода циклов) — строже, чем validate_params.
        for node in self.nodes.values():
            node.validate_structure()

        # 6. Топосортировка и поиск финала
        self.order = self._toposort()
        self.result = self._find_result(out_ports)

    def _check_no_task_in_subgraphs(self) -> None:
        offenders: list[str] = []
        for ns in self.spec.nodes:
            for key, val in (ns.params or {}).items():
                if _looks_like_subgraph(val):
                    offenders += [
                        f"{ns.id}.{key} › {path}"
                        for path in find_task_nodes(val, self.registry)
                    ]
        if offenders:
            raise GraphValidationError(
                "Узлы-задания (с выходом TASK) нельзя размещать внутри тела "
                f"цикла или ветви: {', '.join(offenders)}. Тело отдаёт результат "
                "итерации свободным выходом типа BLOCK, а финальное задание "
                "собирается во внешнем графе."
            )

    def _toposort(self) -> list[str]:
        """Kahn: A зависит от B, если вход A подключён к выходу B."""
        deps: dict[str, set[str]] = {nid: set() for nid in self.nodes}
        dependents: dict[str, set[str]] = {nid: set() for nid in self.nodes}
        for (to_node, _), (from_node, _) in self.in_edges.items():
            if from_node != to_node:
                deps[to_node].add(from_node)
                dependents[from_node].add(to_node)

        ready = [nid for nid, d in deps.items() if not d]
        ready.sort()                       # детерминированный порядок
        order: list[str] = []
        remaining = {nid: set(d) for nid, d in deps.items()}
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for dep in sorted(dependents[nid]):
                remaining[dep].discard(nid)
                if not remaining[dep]:
                    ready.append(dep)
            ready.sort()

        if len(order) != len(self.nodes):
            cyclic = sorted(set(self.nodes) - set(order))
            raise GraphValidationError(f"В графе есть цикл. Узлы: {cyclic}.")
        return order

    def _find_result(self, out_ports: dict[Endpoint, PortType]) -> Endpoint | None:
        """Единственный неподключённый выход типа TASK, если он есть."""
        sinks = [
            ep for ep, t in out_ports.items()
            if t == PortType.TASK and ep not in self.consumed
        ]
        if len(sinks) > 1:
            names = ", ".join(sorted({nid for nid, _port in sinks}))
            raise GraphValidationError(
                f"В графе несколько финальных узлов: свободный выход TASK есть "
                f"сразу у {names}. Финальным может быть только один — удалите "
                f"лишние узлы-задания или оставьте свободным один выход TASK."
            )
        return sinks[0] if sinks else None

    def free_output_of_type(self, port_type: PortType) -> Endpoint | None:
        """
        Единственный неподключённый выход заданного типа, если он есть.

        Используется телом цикла (repeat): «результат итерации» — это свободный
        выход тела нужного типа (по умолчанию BLOCK). Бросает, если их несколько.
        """
        frees = [
            ep for ep, t in self._out_port_types.items()
            if t == port_type and ep not in self.consumed
        ]
        if len(frees) > 1:
            raise GraphValidationError(
                f"В теле цикла несколько свободных выходов типа {port_type.value}: "
                f"{frees}. Оставьте один как результат итерации."
            )
        return frees[0] if frees else None

    # ---------- Исполнение ----------

    def run(self) -> Any:
        """Исполнить граф и вернуть значение финального TASK-узла."""
        if self.result is None:
            raise GraphValidationError(
                "В графе нет финального узла: ни у одного узла нет свободного "
                "выхода типа TASK — нечего возвращать. Добавьте узел-задание "
                "(например, «Статическое задание» или «Числовое задание»)."
            )
        outputs = self.run_full()
        node_id, port = self.result
        return outputs[node_id][port]

    def run_full(self, extra: dict | None = None) -> dict[str, dict[str, Any]]:
        """
        Исполнить граф с whole-graph retry и вернуть выходы ВСЕХ узлов
        успешной попытки. Удобно для тестов и предпросмотра.

        extra — начальное наполнение ExecContext.extra (например, индекс
        итерации, прокидываемый узлом repeat в тело цикла).
        """
        seed = self.spec.meta.get("seed")
        try:
            max_attempts = int(self.spec.meta.get("max_attempts", 100))
        except (TypeError, ValueError):
            max_attempts = 100

        # Воспроизводимость: сидим глобальный random (его использует
        # generation.generate_value) и заводим отдельный rng для контекста.
        if seed is not None:
            random.seed(seed)
        ctx = ExecContext(
            rng=random.Random(seed) if seed is not None else random.Random(),
            extra=dict(extra or {}),
        )

        last: Exception | None = None
        for attempt in range(max_attempts):
            ctx.attempt = attempt
            try:
                return self._execute_once(ctx)
            except RetryGeneration as e:
                last = e
                continue

        raise GraphError(
            f"Не удалось сгенерировать задание за {max_attempts} попыток. "
            f"Последний отказ: {last}"
        )

    def _execute_once(self, ctx: ExecContext) -> dict[str, dict[str, Any]]:
        outputs: dict[str, dict[str, Any]] = {}
        for node_id in self.order:
            node = self.nodes[node_id]
            inputs: dict[str, Any] = {}
            for p in node.input_ports():
                src = self.in_edges.get((node_id, p.name))
                if src is None:
                    continue
                from_node, from_port = src
                value = outputs[from_node][from_port]
                # Авто-повышение типов (BLOCK→BLOCK_LIST и т.п.) — оборачиваем
                # значение при несовпадении типов источника и приёмника.
                src_type = self._out_port_types.get((from_node, from_port))
                if src_type is not None and src_type != p.type:
                    value = coerce_value(value, src_type, p.type)
                inputs[p.name] = value
            outputs[node_id] = node.compute(inputs, ctx)
        return outputs


# ---------- Поиск узлов-заданий во вложенных телах ----------

def _looks_like_subgraph(value: Any) -> bool:
    """Параметр узла является вложенным графом (тело цикла/map, ветвь case)."""
    return isinstance(value, dict) and isinstance(value.get("nodes"), list)


def _output_types(registry: NodeRegistry, type_id: str, params: dict) -> list[PortType]:
    """
    Типы выходных портов узла по его параметрам. Если экземпляр с такими
    параметрами не создаётся (params ещё некорректны) — статический шаблон
    класса; неизвестный тип узла — пусто (его отловит обычная валидация).
    """
    if not registry.has(type_id):
        return []
    cls = registry.get(type_id)
    try:
        ports = cls("_probe", dict(params or {})).output_ports()
    except Exception:
        ports = list(cls.OUTPUTS)
    return [p.type for p in ports]


def find_task_nodes(body: dict, registry: NodeRegistry) -> list[str]:
    """
    id узлов вложенного графа, у которых есть выход типа TASK, — рекурсивно,
    включая подграфы в их параметрах. Вложенность кодируется путём
    'узел.параметр › узел' (как хлебные крошки редактора).
    """
    found: list[str] = []
    for raw in body.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id", "?"))
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        if any(t is PortType.TASK
               for t in _output_types(registry, str(raw.get("type", "")), params)):
            found.append(node_id)
        for key, val in params.items():
            if _looks_like_subgraph(val):
                found += [f"{node_id}.{key} › {path}"
                          for path in find_task_nodes(val, registry)]
    return found
