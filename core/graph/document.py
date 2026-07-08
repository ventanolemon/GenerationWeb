"""
GraphDocument — редактируемая модель графа для визуального редактора.

ЧИСТЫЙ модуль (без Qt): хранит узлы с экранными позициями, рёбра и meta,
сериализуется в тот же GraphSpec-словарь, что исполняет движок. Это позволяет
покрыть логику холста (добавление/удаление узлов и проводов, обрезку висячих
рёбер, round-trip) headless-тестами, не поднимая PyQt6.

Позиции узлов хранятся в meta["layout"] = {node_id: [x, y]} — движок их
игнорирует, формат узла (id/type/params) остаётся прежним.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from .errors import GraphError, GraphValidationError
from .node import Port
from .nodes import DEFAULT_REGISTRY
from .port_types import PortType
from .registry import NodeRegistry
from .spec import GraphSpec


@dataclass
class DocNode:
    """Узел на холсте: тип, параметры, позиция."""
    id: str
    type: str
    params: dict = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0


@dataclass
class DocEdge:
    """Провод: выход одного узла → вход другого."""
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.from_node, self.from_port, self.to_node, self.to_port)


class GraphDocument:
    """Изменяемый граф (узлы + рёбра + meta). Источник правды для редактора."""

    def __init__(self, registry: NodeRegistry | None = None):
        self.registry = registry or DEFAULT_REGISTRY
        self.nodes: dict[str, DocNode] = {}
        self.edges: list[DocEdge] = []
        self.meta: dict = {"max_attempts": 100, "seed": None}
        # Документ — вложенное тело (цикл/map/ветвь case)? Узлы-задания (TASK)
        # там запрещены; редактор помечает их и не даёт добавлять новые.
        self.is_subgraph: bool = False

    # ---------- Идентификаторы ----------

    def unique_id(self, type_id: str) -> str:
        i = 1
        while f"{type_id}_{i}" in self.nodes:
            i += 1
        return f"{type_id}_{i}"

    # ---------- Мутации узлов ----------

    def add_node(self, type_id: str, params: dict | None = None,
                 x: float = 0.0, y: float = 0.0,
                 node_id: str | None = None) -> DocNode:
        if not self.registry.has(type_id):
            raise GraphValidationError(f"Неизвестный тип узла: {type_id!r}")
        nid = node_id or self.unique_id(type_id)
        if nid in self.nodes:
            raise GraphValidationError(f"Узел с id {nid!r} уже существует.")
        node = DocNode(id=nid, type=type_id, params=dict(params or {}),
                       x=float(x), y=float(y))
        self.nodes[nid] = node
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges
                      if e.from_node != node_id and e.to_node != node_id]
        self.set_node_expanded(node_id, False)

    def set_params(self, node_id: str, params: dict) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].params = dict(params)

    def set_pos(self, node_id: str, x: float, y: float) -> None:
        node = self.nodes.get(node_id)
        if node is not None:
            node.x, node.y = float(x), float(y)

    # ---------- Мутации рёбер ----------

    def add_edge(self, from_node: str, from_port: str,
                 to_node: str, to_port: str) -> DocEdge:
        # Один провод на вход: удаляем существующий в (to_node, to_port).
        self.edges = [e for e in self.edges
                      if not (e.to_node == to_node and e.to_port == to_port)]
        edge = DocEdge(from_node, from_port, to_node, to_port)
        self.edges.append(edge)
        return edge

    def remove_edge(self, edge: DocEdge) -> None:
        self.edges = [e for e in self.edges if e.as_tuple() != edge.as_tuple()]

    def edges_for(self, node_id: str) -> list[DocEdge]:
        return [e for e in self.edges
                if e.from_node == node_id or e.to_node == node_id]

    # ---------- Порты ----------

    def ports(self, node_id: str) -> tuple[list[Port], list[Port]]:
        node = self.nodes[node_id]
        return self.safe_ports(node.type, node.params)

    def safe_ports(self, type_id: str, params: dict) -> tuple[list[Port], list[Port]]:
        """
        Порты узла по его параметрам. Для динамических узлов (var_dict/block_list)
        порты зависят от params; если params ещё некорректны — откатываемся к
        статическому шаблону класса, чтобы узел всё равно отрисовался.
        """
        cls = self.registry.get(type_id)
        try:
            inst = cls("_probe", dict(params or {}))
            return list(inst.input_ports()), list(inst.output_ports())
        except Exception:
            return list(cls.INPUTS), list(cls.OUTPUTS)

    def prune_invalid_edges(self) -> None:
        """Удалить рёбра, ссылающиеся на порты, которых больше нет."""
        valid_in: dict[str, set[str]] = {}
        valid_out: dict[str, set[str]] = {}
        for nid, node in self.nodes.items():
            ins, outs = self.safe_ports(node.type, node.params)
            valid_in[nid] = {p.name for p in ins}
            valid_out[nid] = {p.name for p in outs}
        self.edges = [
            e for e in self.edges
            if e.from_node in valid_out and e.from_port in valid_out[e.from_node]
            and e.to_node in valid_in and e.to_port in valid_in[e.to_node]
        ]

    # ---------- Сериализация ----------

    def to_spec_dict(self) -> dict:
        meta = dict(self.meta)
        meta["layout"] = {nid: [n.x, n.y] for nid, n in self.nodes.items()}
        return {
            "version": 1,
            "nodes": [
                {"id": n.id, "type": n.type, "params": n.params}
                for n in self.nodes.values()
            ],
            "edges": [
                {"from": f"{e.from_node}:{e.from_port}",
                 "to": f"{e.to_node}:{e.to_port}"}
                for e in self.edges
            ],
            "meta": meta,
        }

    def to_spec(self) -> GraphSpec:
        return GraphSpec.parse(self.to_spec_dict())

    @classmethod
    def from_spec_dict(cls, data: "str | dict | GraphSpec",
                       registry: NodeRegistry | None = None) -> "GraphDocument":
        spec = GraphSpec.parse(data)
        doc = cls(registry=registry)

        raw_layout = spec.meta.get("layout")
        layout = raw_layout if isinstance(raw_layout, dict) else {}

        doc.meta = {k: v for k, v in spec.meta.items() if k != "layout"}
        doc.meta.setdefault("max_attempts", 100)
        doc.meta.setdefault("seed", None)

        for i, ns in enumerate(spec.nodes):
            pos = layout.get(ns.id)
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                try:
                    x, y = float(pos[0]), float(pos[1])
                except (TypeError, ValueError):
                    x, y = cls.auto_pos(i)
            else:
                x, y = cls.auto_pos(i)
            doc.add_node(ns.type, ns.params, x, y, node_id=ns.id)

        for es in spec.edges:
            doc.edges.append(
                DocEdge(es.from_node, es.from_port, es.to_node, es.to_port)
            )
        return doc

    @staticmethod
    def auto_pos(index: int, cols: int = 4,
                 dx: float = 230, dy: float = 150,
                 x0: float = 40, y0: float = 40) -> tuple[float, float]:
        """Сетка по индексу — раскладка для графов без сохранённых позиций."""
        row, col = divmod(index, cols)
        return (x0 + col * dx, y0 + row * dy)

    # ---------- Валидация ----------

    def validate(self) -> None:
        """Собрать граф движком (полная структурная проверка). Бросает GraphError."""
        from .executor import GraphExecutor
        GraphExecutor(self.to_spec())

    def has_task_sink(self) -> bool:
        """Есть ли финальный узел (неподключённый выход TASK)."""
        from .executor import GraphExecutor
        try:
            return GraphExecutor(self.to_spec()).result is not None
        except GraphError:
            return False

    # ---------- Финальный узел (для подсветки в редакторе) ----------

    def _task_output_ports(self, node_id: str) -> list[str]:
        node = self.nodes[node_id]
        _ins, outs = self.safe_ports(node.type, node.params)
        return [p.name for p in outs if p.type is PortType.TASK]

    def task_node_ids(self) -> list[str]:
        """Все узлы, имеющие выход типа TASK (независимо от подключения)."""
        return [nid for nid in self.nodes if self._task_output_ports(nid)]

    def task_sink_ids(self) -> list[str]:
        """
        Узлы со свободным (никуда не подключённым) выходом TASK — кандидаты
        в финал. Ровно один такой узел = корректный финал графа; несколько —
        конфликт (движок откажется собирать граф).

        В отличие от has_task_sink, не требует валидности всего графа —
        считается прямо по модели, поэтому пригодно для живой подсветки.
        """
        consumed = {(e.from_node, e.from_port) for e in self.edges}
        return [
            nid for nid in self.nodes
            if any((nid, port) not in consumed
                   for port in self._task_output_ports(nid))
        ]

    def type_has_task_output(self, type_id: str) -> bool:
        """Есть ли у типа узла (с параметрами по умолчанию) выход TASK."""
        if not self.registry.has(type_id):
            return False
        _ins, outs = self.safe_ports(type_id, {})
        return any(p.type is PortType.TASK for p in outs)

    # ---------- Развёрнутые рамки циклов (состояние вида, в meta) ----------
    #
    # Развёрнутый узел цикла рисуется на холсте рамкой-структурой с телом
    # внутри (LabVIEW-style). Список id хранится в meta["expanded_nodes"]:
    # движок исполнения meta не интерпретирует, а сериализация общая.

    def expanded_nodes(self) -> set[str]:
        raw = self.meta.get("expanded_nodes")
        return {str(x) for x in raw} if isinstance(raw, list) else set()

    def is_node_expanded(self, node_id: str) -> bool:
        return node_id in self.expanded_nodes()

    def set_node_expanded(self, node_id: str, expanded: bool) -> None:
        cur = self.expanded_nodes()
        if expanded:
            cur.add(node_id)
        else:
            cur.discard(node_id)
        if cur:
            self.meta["expanded_nodes"] = sorted(cur)
        else:
            self.meta.pop("expanded_nodes", None)
