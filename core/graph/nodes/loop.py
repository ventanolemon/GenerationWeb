"""
Узлы цикла (категория control, scoped-loop).

repeat — агрегатор: исполняет своё ТЕЛО (вложенный граф в params["body"]) N раз
и собирает результаты в список. Тело — это полноценный GraphSpec со своими
узлами; его «результат итерации» — единственный свободный выход типа BLOCK.
Внутри тела доступен узел loop_index, отдающий номер текущей итерации (0..N-1),
что позволяет делать строки таблицы/подзадачи, зависящие от номера.

Туннели вывода (как выходные туннели LabVIEW): объявление в params["outputs"]
('имя:тип:режим') добавляет внешнему узлу выходной порт, а узел output_var с
тем же именем в теле задаёт его значение; режим list — индексированный сбор
значений всех итераций, last — значение последней итерации. Для значений
любого типа — числа и строки больше не нужно упаковывать в блоки или регистры.

Реализация не трогает планировщик внешнего графа: repeat — обычная вершина
внешнего DAG (count:NUMBER → out:BLOCK_LIST), а тело исполняется отдельным
GraphExecutor внутри compute(). Так вложенность получается естественно и без
псевдоциклов в основном исполнителе.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


# Ключ в ExecContext.extra, под которым repeat кладёт индекс итерации.
LOOP_INDEX_KEY = "__loop_index__"

# Префикс ключа в ExecContext.extra для значений внешних переменных (import-
# туннелей), прокинутых из объемлющего графа в тело цикла/map.
IMPORT_PREFIX = "__import__"

# Типы, которые умеет переносить import-туннель (имя в UI → PortType).
_IMPORT_TYPES = {
    "number": PortType.NUMBER,
    "string": PortType.STRING,
    "number_dict": PortType.NUMBER_DICT,
    "bool": PortType.BOOL,
    "block": PortType.BLOCK,
    "list": PortType.LIST,
}


def parse_imports(params: dict) -> list[tuple[str, PortType]]:
    """
    Разобрать параметр imports ['имя:тип', ...] в список (имя, PortType).

    Тип по умолчанию — number. Неизвестный тип → GraphValidationError.
    Пустые элементы пропускаются; имена обязаны быть уникальны.
    """
    specs = params.get("imports") or []
    out: list[tuple[str, PortType]] = []
    seen: set[str] = set()
    for raw in specs:
        s = str(raw).strip()
        if not s:
            continue
        name, _, tname = s.partition(":")
        name = name.strip()
        tname = (tname.strip() or "number")
        if not name:
            continue
        if tname not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Внешняя переменная {s!r}: неизвестный тип {tname!r}. "
                f"Допустимы: {list(_IMPORT_TYPES)}"
            )
        if name in seen:
            raise GraphValidationError(
                f"Внешняя переменная {name!r} объявлена дважды."
            )
        seen.add(name)
        out.append((name, _IMPORT_TYPES[tname]))
    return out


class InputVarNode(Node):
    """
    Внешняя переменная внутри тела цикла/map: читает значение import-туннеля
    по имени (объявленному в параметре imports объемлющего repeat/map).

    Тип выхода задаётся параметром type и должен совпадать с типом туннеля.
    """
    type_id = "input_var"
    category = "control"
    display_name = "Внешняя переменная"
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "x"},
        "type": {"type": "enum", "values": list(_IMPORT_TYPES), "default": "number"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "number")
        if t not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип {t!r}. "
                f"Допустимы: {list(_IMPORT_TYPES)}"
            )

    def output_ports(self):
        return [Port("out", _IMPORT_TYPES.get(self.params.get("type", "number"),
                                              PortType.NUMBER))]

    def compute(self, inputs, ctx: ExecContext):
        name = str(self.params.get("name", "x"))
        key = IMPORT_PREFIX + name
        if key not in ctx.extra:
            raise RetryGeneration(
                f"input_var {self.node_id!r}: внешняя переменная {name!r} "
                f"не передана (нет туннеля с таким именем)."
            )
        return {"out": ctx.extra[key]}


def _import_extra(node, inputs) -> dict:
    """Собрать значения import-туннелей из входов внешнего узла в extra-словарь."""
    extra: dict = {}
    for name, _t in parse_imports(node.params):
        if name in inputs:
            extra[IMPORT_PREFIX + name] = inputs[name]
    return extra


# Префикс ключа extra для значений регистров сдвига (состояние между итерациями).
REGISTER_PREFIX = "__register__"


# Режимы туннеля вывода (как у выходных туннелей LabVIEW):
#   list — индексированный сбор: значения всех итераций складываются в список;
#   last — последнее значение (значение завершающей итерации).
_OUTPUT_MODES = ("list", "last")


def parse_outputs(params: dict) -> list[tuple[str, PortType, str]]:
    """
    Разобрать параметр outputs ['имя[:тип[:режим]]', ...] в (имя, PortType, режим).

    Тип по умолчанию number, режим — list (индексированный сбор по итерациям);
    'last' — значение последней итерации. Имена уникальны и не равны 'out'
    (встроенный выход блоков цикла).
    """
    specs = params.get("outputs") or []
    out: list[tuple[str, PortType, str]] = []
    seen: set[str] = set()
    for raw in specs:
        s = str(raw).strip()
        if not s:
            continue
        parts = [p.strip() for p in s.split(":")]
        name = parts[0]
        tname = parts[1] if len(parts) > 1 and parts[1] else "number"
        mode = parts[2] if len(parts) > 2 and parts[2] else "list"
        if not name:
            continue
        if name == "out":
            raise GraphValidationError(
                "Туннель вывода не может называться 'out' — "
                "это встроенный выход блоков цикла."
            )
        if tname not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Туннель вывода {s!r}: неизвестный тип {tname!r}. "
                f"Допустимы: {list(_IMPORT_TYPES)}"
            )
        if mode not in _OUTPUT_MODES:
            raise GraphValidationError(
                f"Туннель вывода {s!r}: неизвестный режим {mode!r}. Допустимы: "
                f"list (собрать значения всех итераций) и last (последнее)."
            )
        if name in seen:
            raise GraphValidationError(f"Туннель вывода {name!r} объявлен дважды.")
        seen.add(name)
        out.append((name, _IMPORT_TYPES[tname], mode))
    return out


def _tunnel_port(name: str, t: PortType, mode: str) -> Port:
    """Выходной порт туннеля на внешнем узле цикла."""
    if mode == "last":
        return Port(name, t)
    # Индексированный сбор: блоки — в BLOCK_LIST, остальное — в LIST.
    return Port(name, PortType.BLOCK_LIST if t is PortType.BLOCK else PortType.LIST)


def _tunnel_nodes(body: dict) -> dict[str, tuple[str, str]]:
    """Туннели в теле: имя → (id узла output_var, его тип-параметр)."""
    out: dict[str, tuple[str, str]] = {}
    for node in (body.get("nodes") or []) if isinstance(body, dict) else []:
        if node.get("type") != "output_var" or "id" not in node:
            continue
        params = node.get("params") or {}
        name = str(params.get("name", "result"))
        out[name] = (node["id"], str(params.get("type", "number")))
    return out


def _check_tunnels(node_id: str, params: dict, body: dict, where: str) -> None:
    """
    Объявленные туннели вывода должны иметь в теле узел output_var с тем же
    именем и типом. Вызывается из validate_structure (а не validate_params),
    чтобы редактор оставался терпим к недособранному графу при отрисовке.
    """
    available = _tunnel_nodes(body)
    for name, t, _mode in parse_outputs(params):
        if name not in available:
            raise GraphValidationError(
                f"Узел {node_id!r}: туннель вывода {name!r} объявлен, но {where} "
                f"нет узла «Выход цикла (туннель)» (output_var) с именем {name!r}."
            )
        if _IMPORT_TYPES.get(available[name][1]) is not t:
            raise GraphValidationError(
                f"Узел {node_id!r}: туннель {name!r} объявлен с типом {t.value!r}, "
                f"а узел output_var {where} имеет тип {available[name][1]!r}."
            )


def _collect_tunnel(tunnels: dict, outputs: dict,
                    tunnel_nodes: dict[str, tuple[str, str]],
                    declarations: list[tuple[str, PortType, str]]) -> None:
    """Забрать значения туннелей из выходов итерации (list — добавить, last — заменить)."""
    for name, _t, mode in declarations:
        entry = tunnel_nodes.get(name)
        if entry is None or entry[0] not in outputs:
            continue          # отсутствие узла отлавливает validate_structure
        val = outputs[entry[0]].get("out")
        if mode == "list":
            tunnels[name].append(val)
        else:
            tunnels[name] = val


class OutputVarNode(Node):
    """
    Туннель вывода внутри тела цикла/map/ветви case: значение, проведённое в
    этот узел, выходит из цикла наружу — одноимённым портом на внешнем узле
    (объявляется в его параметре outputs: 'имя:тип:режим'). Режим объявления
    определяет, что окажется снаружи: список значений всех итераций (list,
    индексированный туннель) или значение последней итерации (last).

    Чистый приёмник: выходных портов нет, чтобы не конкурировать со свободным
    BLOCK-выходом тела («результат итерации»). Значение объемлющий цикл
    забирает из внутреннего результата compute (ключ 'out').
    """
    type_id = "output_var"
    category = "control"
    display_name = "Выход цикла (туннель)"
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "result"},
        "type": {"type": "enum", "values": list(_IMPORT_TYPES), "default": "number"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "number")
        if t not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип {t!r}. "
                f"Допустимы: {list(_IMPORT_TYPES)}"
            )

    def _t(self) -> PortType:
        return _IMPORT_TYPES.get(self.params.get("type", "number"), PortType.NUMBER)

    def input_ports(self):
        return [Port("value", self._t())]

    def compute(self, inputs, ctx: ExecContext):
        # Невидимый снаружи выход: исполнитель сохранит его в outputs узла,
        # откуда значение заберёт объемлющий repeat/map/case.
        return {"out": inputs.get("value")}


def parse_registers(params: dict) -> list[tuple[str, PortType, object]]:
    """
    Разобрать параметр registers ['имя:тип:начальное', ...].

    Тип по умолчанию number, начальное значение опционально. Возвращает список
    (имя, PortType, начальное_сырое|None). Имена уникальны, тип из _IMPORT_TYPES.
    """
    specs = params.get("registers") or []
    out: list[tuple[str, PortType, object]] = []
    seen: set[str] = set()
    for raw in specs:
        s = str(raw).strip()
        if not s:
            continue
        parts = s.split(":")
        name = parts[0].strip()
        tname = (parts[1].strip() if len(parts) > 1 and parts[1].strip() else "number")
        initial = parts[2] if len(parts) > 2 else None
        if not name:
            continue
        if tname not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Регистр {s!r}: неизвестный тип {tname!r}. "
                f"Допустимы: {list(_IMPORT_TYPES)}"
            )
        if name in seen:
            raise GraphValidationError(f"Регистр {name!r} объявлен дважды.")
        seen.add(name)
        out.append((name, _IMPORT_TYPES[tname], initial))
    return out


def _register_initial(ptype: PortType, raw) -> object:
    """Начальное значение регистра по типу (для итерации 0)."""
    if ptype is PortType.NUMBER:
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    if ptype is PortType.STRING:
        return "" if raw is None else str(raw)
    return raw  # для прочих типов начальное = как передано (обычно None)


class ShiftGetNode(Node):
    """
    Регистр сдвига — чтение: значение с предыдущей итерации цикла (на итерации 0
    — начальное значение, объявленное в registers объемлющего repeat). Источник.
    """
    type_id = "shift_get"
    category = "control"
    display_name = "Регистр: чтение"
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "acc"},
        "type": {"type": "enum", "values": list(_IMPORT_TYPES), "default": "number"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "number")
        if t not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип {t!r}."
            )

    def output_ports(self):
        return [Port("out", _IMPORT_TYPES.get(self.params.get("type", "number"),
                                              PortType.NUMBER))]

    def compute(self, inputs, ctx: ExecContext):
        name = str(self.params.get("name", "acc"))
        key = REGISTER_PREFIX + name
        if key not in ctx.extra:
            raise RetryGeneration(
                f"shift_get {self.node_id!r}: регистр {name!r} не объявлен в repeat."
            )
        return {"out": ctx.extra[key]}


class ShiftSetNode(Node):
    """
    Регистр сдвига — запись: значение, которое получит следующая итерация.
    Проходной выход (out = value) — чтобы исполнитель записал его, а repeat забрал
    после итерации. Тип out совпадает с типом value.
    """
    type_id = "shift_set"
    category = "control"
    display_name = "Регистр: запись"
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "acc"},
        "type": {"type": "enum", "values": list(_IMPORT_TYPES), "default": "number"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "number")
        if t not in _IMPORT_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип {t!r}."
            )

    def _t(self) -> PortType:
        return _IMPORT_TYPES.get(self.params.get("type", "number"), PortType.NUMBER)

    def input_ports(self):
        return [Port("value", self._t())]

    def output_ports(self):
        return [Port("out", self._t())]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": inputs.get("value")}


class LoopIndexNode(Node):
    """Номер текущей итерации цикла (0-based). Источник внутри тела repeat."""
    type_id = "loop_index"
    category = "control"
    display_name = "Индекс итерации"
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(ctx.extra.get(LOOP_INDEX_KEY, 0))}


class RepeatNode(Node):
    """
    Повторить тело N раз, собрать BLOCK-результаты итераций в BLOCK_LIST.

    Параметры:
      body         — вложенный граф (dict со spec: nodes/edges/meta);
      max_iterations — потолок N (защита от опечатки в count);
      outputs      — туннели вывода ['имя:тип:режим', ...]: каждый добавляет
                     выходной порт; значение в теле задаёт узел output_var
                     с тем же именем. Режим list (по умолчанию) собирает
                     значения всех итераций в список (LIST; блоки —
                     в BLOCK_LIST), режим last отдаёт значение последней.
    Вход count (NUMBER) задаёт число повторов; если не подключён — берётся
    параметр count.
    """
    type_id = "repeat"
    category = "control"
    display_name = "Повторить (цикл)"
    INPUTS = [Port("count", PortType.NUMBER, required=False)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "count": {"type": "int", "default": 3},
        "max_iterations": {"type": "int", "default": 1000, "optional": True},
        "imports": {"type": "list", "default": [], "optional": True},
        "outputs": {"type": "list", "default": [], "optional": True},
        "registers": {"type": "list", "default": [], "optional": True},
        "body": {"type": "subgraph", "default": {"nodes": [], "edges": [], "meta": {}}},
    }

    def validate_params(self) -> None:
        body = self.params.get("body")
        if body is not None and not isinstance(body, dict):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'body' должен быть вложенным графом (объектом)."
            )
        parse_imports(self.params)    # формат объявлений внешних переменных
        # Имя туннеля не должно совпадать с портом регистра reg_<имя>.
        reg_ports = {f"reg_{name}"
                     for name, _t, _i in parse_registers(self.params)}
        for name, _t, _m in parse_outputs(self.params):
            if name in reg_ports:
                raise GraphValidationError(
                    f"Узел {self.node_id!r}: туннель вывода {name!r} совпадает "
                    f"с выходом регистра — переименуйте туннель или регистр."
                )

    def validate_structure(self) -> None:
        _check_tunnels(self.node_id, self.params,
                       self.params.get("body") or {}, "в теле")

    def input_ports(self):
        # count + по одному (необязательному) входу на каждую внешнюю переменную.
        ports = [Port("count", PortType.NUMBER, required=False)]
        for name, t in parse_imports(self.params):
            ports.append(Port(name, t, required=False))
        return ports

    def output_ports(self):
        # out (блоки итераций) + по порту на каждый туннель вывода + по выходу
        # reg_<имя> на каждый регистр — его ФИНАЛЬНОЕ значение после всех
        # итераций (накопленное/последнее, например list-регистр со списком).
        ports = [Port("out", PortType.BLOCK_LIST)]
        for name, t, mode in parse_outputs(self.params):
            ports.append(_tunnel_port(name, t, mode))
        for name, t, _init in parse_registers(self.params):
            ports.append(Port(f"reg_{name}", t))
        return ports

    def _count(self, inputs) -> int:
        raw = inputs.get("count", self.params.get("count", 3))
        try:
            n = int(round(float(raw)))
        except (TypeError, ValueError):
            raise RetryGeneration(f"repeat {self.node_id!r}: count не число ({raw!r}).")
        try:
            cap = int(self.params.get("max_iterations", 1000))
        except (TypeError, ValueError):
            cap = 1000
        return max(0, min(n, cap))

    def compute(self, inputs, ctx: ExecContext):
        # Импорт здесь, чтобы избежать цикла импорта executor↔nodes на загрузке.
        from ..executor import GraphExecutor
        from ..spec import GraphSpec

        body = self.params.get("body") or {"nodes": [], "edges": [], "meta": {}}
        spec = GraphSpec.parse(body)

        n = self._count(inputs)
        imports = _import_extra(self, inputs)

        # Регистры сдвига: начальные значения для итерации 0. Каждое объявление
        # registers[name] переносит результат прошлой итерации в следующую.
        registers = parse_registers(self.params)
        reg_state: dict[str, object] = {
            name: _register_initial(t, init) for name, t, init in registers
        }
        # Соответствие name -> id узла shift_set в теле (откуда забирать новое
        # значение регистра после итерации).
        setters = {
            node.get("params", {}).get("name", "acc"): node["id"]
            for node in (body.get("nodes") or [])
            if node.get("type") == "shift_set"
        }

        # Туннели вывода: list стартует пустым, last — типовым значением
        # по умолчанию (актуально только при 0 итераций).
        declarations = parse_outputs(self.params)
        tunnel_src = _tunnel_nodes(body)
        tunnels: dict[str, object] = {
            name: ([] if mode == "list" else _register_initial(t, None))
            for name, t, mode in declarations
        }

        collected: list = []
        for i in range(n):
            ex = GraphExecutor(spec, registry=self._registry())
            result_ep = ex.free_output_of_type(PortType.BLOCK)
            reg_extra = {REGISTER_PREFIX + name: val for name, val in reg_state.items()}
            outputs = ex.run_full(extra={**imports, **reg_extra, LOOP_INDEX_KEY: i})
            if result_ep is not None:
                node_id, port = result_ep
                collected.append(outputs[node_id][port])
            _collect_tunnel(tunnels, outputs, tunnel_src, declarations)
            # Обновить регистры значениями shift_set для следующей итерации.
            for name in reg_state:
                sid = setters.get(name)
                if sid is not None and sid in outputs and "out" in outputs[sid]:
                    reg_state[name] = outputs[sid]["out"]
        # Помимо собранных блоков — значения туннелей вывода и финальное
        # значение каждого регистра (выход reg_<имя>).
        result = {"out": collected, **tunnels}
        for name in reg_state:
            result[f"reg_{name}"] = reg_state[name]
        return result

    def _registry(self):
        # Тело использует тот же реестр узлов, что и внешний граф.
        from . import DEFAULT_REGISTRY
        return DEFAULT_REGISTRY


# Ключ в ExecContext.extra, под которым map кладёт текущий элемент.
MAP_ITEM_KEY = "__map_item__"

# Типы элемента, которые map_item умеет отдавать в тело.
_ITEM_TYPES = {
    "number": PortType.NUMBER,
    "string": PortType.STRING,
    "block": PortType.BLOCK,
}


class MapItemNode(Node):
    """Текущий элемент коллекции внутри тела map. Источник."""
    type_id = "map_item"
    category = "control"
    display_name = "Элемент (map)"
    PARAMS_SCHEMA = {
        "type": {"type": "enum", "values": list(_ITEM_TYPES), "default": "string"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "string")
        if t not in _ITEM_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип элемента {t!r}. "
                f"Допустимы: {list(_ITEM_TYPES)}"
            )

    def output_ports(self):
        return [Port("out", _ITEM_TYPES.get(self.params.get("type", "string"),
                                            PortType.STRING))]

    def compute(self, inputs, ctx: ExecContext):
        v = ctx.extra.get(MAP_ITEM_KEY)
        t = self.params.get("type", "string")
        if t == "number":
            try:
                return {"out": float(v)}
            except (TypeError, ValueError):
                raise RetryGeneration(
                    f"map_item {self.node_id!r}: элемент {v!r} не число."
                )
        if t == "string":
            return {"out": "" if v is None else str(v)}
        return {"out": v}  # block — передаём как есть


class MapNode(Node):
    """
    Применить тело к каждому элементу входного списка, собрать BLOCK-результаты
    в BLOCK_LIST.

    Вход items:LIST — коллекция. Внутри тела доступны map_item (текущий элемент)
    и loop_index (его индекс 0..N-1). Результат итерации — свободный выход тела
    типа BLOCK. Тело хранится в params['body'] (вложенный граф) и исполняется
    отдельным GraphExecutor по образцу repeat. Туннели вывода (params['outputs']
    + узел output_var в теле) работают как у repeat: режим list собирает
    значения по элементам, last отдаёт значение последнего.
    """
    type_id = "map"
    category = "control"
    display_name = "Map (по списку)"
    INPUTS = [Port("items", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "imports": {"type": "list", "default": [], "optional": True},
        "outputs": {"type": "list", "default": [], "optional": True},
        "body": {"type": "subgraph", "default": {"nodes": [], "edges": [], "meta": {}}},
    }

    def validate_params(self) -> None:
        body = self.params.get("body")
        if body is not None and not isinstance(body, dict):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'body' должен быть вложенным графом (объектом)."
            )
        parse_imports(self.params)
        parse_outputs(self.params)

    def validate_structure(self) -> None:
        _check_tunnels(self.node_id, self.params,
                       self.params.get("body") or {}, "в теле")

    def input_ports(self):
        ports = [Port("items", PortType.LIST)]
        for name, t in parse_imports(self.params):
            ports.append(Port(name, t, required=False))
        return ports

    def output_ports(self):
        ports = [Port("out", PortType.BLOCK_LIST)]
        for name, t, mode in parse_outputs(self.params):
            ports.append(_tunnel_port(name, t, mode))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from ..executor import GraphExecutor
        from ..spec import GraphSpec

        body = self.params.get("body") or {"nodes": [], "edges": [], "meta": {}}
        spec = GraphSpec.parse(body)

        items = inputs.get("items") or []
        if not isinstance(items, (list, tuple)):
            raise RetryGeneration(
                f"map {self.node_id!r}: на вход items пришёл не список ({type(items).__name__})."
            )

        from . import DEFAULT_REGISTRY
        imports = _import_extra(self, inputs)
        declarations = parse_outputs(self.params)
        tunnel_src = _tunnel_nodes(body)
        tunnels: dict[str, object] = {
            name: ([] if mode == "list" else _register_initial(t, None))
            for name, t, mode in declarations
        }
        collected: list = []
        for i, el in enumerate(items):
            ex = GraphExecutor(spec, registry=DEFAULT_REGISTRY)
            result_ep = ex.free_output_of_type(PortType.BLOCK)
            outputs = ex.run_full(extra={**imports, MAP_ITEM_KEY: el, LOOP_INDEX_KEY: i})
            if result_ep is not None:
                node_id, port = result_ep
                collected.append(outputs[node_id][port])
            _collect_tunnel(tunnels, outputs, tunnel_src, declarations)
        return {"out": collected, **tunnels}


def _branch_run(spec, extra: dict) -> tuple[list, dict]:
    """
    Исполнить ветвь-подграф, вернуть (блоки ветви, выходы всех её узлов).

    Блоки ветви — свободный выход типа BLOCK_LIST (используется как есть)
    либо свободный BLOCK (оборачивается в список из одного элемента); нет
    блочного выхода — пустой список. Выходы узлов нужны вызывающему, чтобы
    забрать значения туннелей из ТОГО ЖЕ запуска (повторный запуск дал бы
    другие случайные значения).
    """
    from ..executor import GraphExecutor
    from . import DEFAULT_REGISTRY

    ex = GraphExecutor(spec, registry=DEFAULT_REGISTRY)
    list_ep = ex.free_output_of_type(PortType.BLOCK_LIST)
    block_ep = None if list_ep is not None else ex.free_output_of_type(PortType.BLOCK)
    outputs = ex.run_full(extra=extra)
    if list_ep is not None:
        node_id, port = list_ep
        val = outputs[node_id][port]
        blocks = list(val) if isinstance(val, (list, tuple)) else [val]
    elif block_ep is not None:
        node_id, port = block_ep
        blocks = [outputs[node_id][port]]
    else:
        blocks = []
    return blocks, outputs


class CaseNode(Node):
    """
    Кейс-структура: по числовому селектору исполняет ОДНУ из нескольких ветвей
    (каждая — отдельный вложенный граф), а не все сразу.

    Параметры:
      cases   — число ветвей N (ветви хранятся под ключами case_0..case_{N-1});
      imports — внешние переменные (как у repeat/map), доступны во всех ветвях;
      default — ветвь для селектора вне диапазона [0; N) (ключ 'default');
      outputs — туннели вывода ['имя:тип', ...]: порт получает значение
                output_var исполненной ветви (режим не используется — ветвь
                исполняется один раз). Туннель обязан быть в каждой ветви.
    Вход selector:NUMBER — индекс ветви. Выход out:BLOCK_LIST — блоки выбранной
    ветви (свободный BLOCK_LIST ветви как есть, либо одиночный BLOCK в списке).

    В отличие от select (жадный мультиплексор, считает обе ветви), здесь
    исполняется только выбранная ветвь — это настоящий условный поток.
    """
    type_id = "case"
    category = "control"
    display_name = "Кейс (выбор ветви)"
    INPUTS = [Port("selector", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "cases": {"type": "int", "default": 2},
        "imports": {"type": "list", "default": [], "optional": True},
        "outputs": {"type": "list", "default": [], "optional": True},
        # Спец-поле: инспектор разворачивает в кнопки по числу ветвей + default.
        "branches": {"type": "case_bodies", "default": None},
    }

    def validate_params(self) -> None:
        parse_imports(self.params)
        parse_outputs(self.params)
        for key in self.branch_keys() + ["default"]:
            body = self.params.get(key)
            if body is not None and not isinstance(body, dict):
                raise GraphValidationError(
                    f"Узел {self.node_id!r}: ветвь {key!r} должна быть "
                    f"вложенным графом (объектом)."
                )

    def validate_structure(self) -> None:
        # Туннели обязаны быть в каждой нумерованной ветви; в default — только
        # если она не пуста (пустая default с туннелем даст ошибку при
        # исполнении, если селектор выйдет за диапазон).
        if not parse_outputs(self.params):
            return
        for key in self.branch_keys():
            _check_tunnels(self.node_id, self.params,
                           self.params.get(key) or {}, f"в ветви {key!r}")
        default = self.params.get("default") or {}
        if default.get("nodes"):
            _check_tunnels(self.node_id, self.params, default, "в ветви 'default'")

    def _case_count(self) -> int:
        try:
            return max(0, int(self.params.get("cases", 2)))
        except (TypeError, ValueError):
            return 2

    def branch_keys(self) -> list[str]:
        return [f"case_{i}" for i in range(self._case_count())]

    def input_ports(self):
        ports = [Port("selector", PortType.NUMBER)]
        for name, t in parse_imports(self.params):
            ports.append(Port(name, t, required=False))
        return ports

    def output_ports(self):
        # Ветвь исполняется один раз, поэтому туннель case отдаёт значение
        # как есть (режим объявления не используется).
        ports = [Port("out", PortType.BLOCK_LIST)]
        for name, t, _mode in parse_outputs(self.params):
            ports.append(Port(name, t))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from ..spec import GraphSpec

        n = self._case_count()
        try:
            sel = int(round(float(inputs.get("selector", 0))))
        except (TypeError, ValueError):
            raise RetryGeneration(
                f"case {self.node_id!r}: selector не число ({inputs.get('selector')!r})."
            )

        key = f"case_{sel}" if 0 <= sel < n else "default"
        body = self.params.get(key) or {"nodes": [], "edges": [], "meta": {}}
        spec = GraphSpec.parse(body)
        imports = _import_extra(self, inputs)
        blocks, outputs = _branch_run(spec, imports)

        tunnels: dict[str, object] = {}
        available = _tunnel_nodes(body)
        for name, _t, _mode in parse_outputs(self.params):
            entry = available.get(name)
            if entry is None or entry[0] not in outputs:
                raise GraphValidationError(
                    f"case {self.node_id!r}: исполнена ветвь {key!r}, но в ней "
                    f"нет туннеля вывода {name!r} (узла output_var)."
                )
            tunnels[name] = outputs[entry[0]].get("out")
        return {"out": blocks, **tunnels}
