"""
Узлы для работы со списками (категория list).

Тип PortType.LIST — это list[Any]: список значений любого типа (числа, строки,
блоки, матрицы…). Эти узлы дают базовые операции, которых не хватало для
накопления значений в цикле:

  list_new    — создать список (пустой или из элементов-литералов);
  list_append — добавить элемент в конец (возвращает НОВЫЙ список);
  list_length — длина списка → NUMBER;
  list_get    — элемент по индексу;
  list_join   — склейка элементов списка в строку (для строк/чисел).

Связка с циклом: объявите в repeat регистр типа list (например 'acc:list'),
внутри тела на каждой итерации читайте его (shift_get), добавляйте элемент
(list_append) и пишите обратно (shift_set). После цикла выход repeat reg_acc
отдаст накопленный список. Так из цикла «выводятся» значения многих итераций.
"""

from __future__ import annotations

from ..errors import RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


_ELEM_TYPES = {
    "number": PortType.NUMBER,
    "string": PortType.STRING,
    "bool": PortType.BOOL,
    "block": PortType.BLOCK,
    "expr": PortType.EXPR,
    "matrix": PortType.MATRIX,
}


class ListNewNode(Node):
    """
    Создать список. count>0 — динамические входы in0..inN (тип elem_type)
    собираются в список. Иначе — из текстовых items (числа распознаются).
    Источник/сборщик LIST.
    """
    type_id = "list_new"
    category = "list"
    display_name = "Создать список"
    description = ("Создать список из N входов (тип elem_type) или из items. "
                   "Выход: LIST.")
    OUTPUTS = [Port("out", PortType.LIST)]
    PARAMS_SCHEMA = {
        "count": {"type": "int", "default": 0},
        "elem_type": {"type": "enum", "values": list(_ELEM_TYPES),
                      "default": "number", "optional": True},
        "items": {"type": "list", "default": [], "optional": True},
    }

    def _count(self) -> int:
        try:
            return max(0, int(self.params.get("count", 0)))
        except (TypeError, ValueError):
            return 0

    def input_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port(f"in{i}", et, required=False) for i in range(self._count())]

    def compute(self, inputs, ctx: ExecContext):
        if self._count() > 0:
            return {"out": [inputs[f"in{i}"] for i in range(self._count())
                            if f"in{i}" in inputs]}
        # Иначе — из текстовых items (числа распознаём, иначе строка).
        out = []
        for raw in (self.params.get("items") or []):
            s = str(raw)
            try:
                out.append(float(s) if ("." in s or "e" in s.lower()) else int(s))
            except ValueError:
                out.append(s)
        return {"out": out}


class ListAppendNode(Node):
    """
    Добавить элемент в конец списка → НОВЫЙ список (исходный не мутируется).
    Тип элемента — параметр elem_type (вход item получает этот тип).
    """
    type_id = "list_append"
    category = "list"
    display_name = "Добавить в список"
    description = ("Добавить элемент в конец списка (новый список). "
                   "Вход: list (LIST), item. Выход: LIST.")
    OUTPUTS = [Port("out", PortType.LIST)]
    PARAMS_SCHEMA = {
        "elem_type": {"type": "enum", "values": list(_ELEM_TYPES),
                      "default": "number", "optional": True},
    }

    def input_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port("list", PortType.LIST, required=False), Port("item", et)]

    def compute(self, inputs, ctx: ExecContext):
        base = _as_list(inputs.get("list"))
        base.append(inputs.get("item"))
        return {"out": base}


class ListLengthNode(Node):
    """Длина списка (LIST → NUMBER)."""
    type_id = "list_length"
    category = "list"
    display_name = "Длина списка"
    description = "Число элементов списка. Вход: LIST. Выход: NUMBER."
    INPUTS = [Port("in", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(len(_as_list(inputs.get("in"))))}


class ListGetNode(Node):
    """
    Элемент списка по индексу (LIST + NUMBER → элемент). Тип элемента — elem_type.
    Отрицательный индекс — с конца. Выход за границы → RetryGeneration.
    """
    type_id = "list_get"
    category = "list"
    display_name = "Элемент списка"
    description = ("Элемент по индексу (отрицательный — с конца). "
                   "Вход: list (LIST), index (NUMBER). Выход: по типу.")
    PARAMS_SCHEMA = {
        "elem_type": {"type": "enum", "values": list(_ELEM_TYPES),
                      "default": "number", "optional": True},
        "index": {"type": "int", "default": -1, "optional": True},
    }
    INPUTS = [Port("list", PortType.LIST), Port("index", PortType.NUMBER, required=False)]

    def output_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port("out", et)]

    def compute(self, inputs, ctx: ExecContext):
        items = _as_list(inputs.get("list"))
        if "index" in inputs and inputs["index"] is not None:
            idx = int(round(float(inputs["index"])))
        else:
            idx = int(self.params.get("index", -1))
        if not items or not (-len(items) <= idx < len(items)):
            raise RetryGeneration(
                f"list_get {self.node_id!r}: индекс {idx} вне диапазона (len={len(items)})."
            )
        return {"out": items[idx]}


class RandomChoiceNode(Node):
    """
    Случайный выбор одного элемента из набора — «пул вариантов» одним узлом.

    Набор берётся из входа list (LIST), а если он не подключён — из параметра
    items (текстовые литералы). Выбранный элемент приводится к типу elem_type
    (number/string/expr/matrix/bool/block), поэтому результат можно сразу
    подать дальше: строку — в маркер #имя# текста, выражение — в diff/limit и т.п.
    Воспроизводимо через ctx.rng (как random_natural).

    Покрывает самый частый паттерн реальных генераторов (пулы эквивалентностей,
    варианты функций) без связки list_new + random_natural + list_get.
    """
    type_id = "random_choice"
    category = "source"
    display_name = "Случайный выбор"
    description = ("Случайно выбрать элемент из набора (вход LIST или параметр "
                   "items). Тип выхода — elem_type. Источник варианта.")
    INPUTS = [Port("list", PortType.LIST, required=False)]
    PARAMS_SCHEMA = {
        "elem_type": {"type": "enum", "values": list(_ELEM_TYPES),
                      "default": "string", "optional": True},
        "items": {"type": "list", "default": [], "optional": True},
    }

    def output_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "string"), PortType.STRING)
        return [Port("out", et)]

    def _coerce(self, value):
        et = self.params.get("elem_type", "string")
        if et == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise RetryGeneration(
                    f"random_choice {self.node_id!r}: элемент {value!r} не число."
                )
        if et == "string":
            return _fmt(value) if isinstance(value, (int, float)) else str(value)
        if et == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "да", "yes")
            return bool(value)
        if et == "expr":
            from ..symbolic import as_expr
            return as_expr(value)
        if et == "matrix":
            from ..symbolic import as_matrix
            return as_matrix(value)
        return value      # block — как есть

    def compute(self, inputs, ctx: ExecContext):
        items = _as_list(inputs.get("list"))
        if not items:
            items = list(self.params.get("items") or [])
        if not items:
            raise RetryGeneration(
                f"random_choice {self.node_id!r}: пустой набор для выбора."
            )
        return {"out": self._coerce(ctx.rng.choice(items))}


class ListJoinNode(Node):
    """Склеить элементы списка в строку через разделитель (LIST → STRING)."""
    type_id = "list_join"
    category = "list"
    display_name = "Склеить список"
    description = ("Объединить элементы списка в строку через разделитель. "
                   "Вход: LIST. Выход: STRING.")
    INPUTS = [Port("in", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.STRING)]
    PARAMS_SCHEMA = {"sep": {"type": "string", "default": ", ", "optional": True}}

    def compute(self, inputs, ctx: ExecContext):
        sep = str(self.params.get("sep", ", "))
        items = _as_list(inputs.get("in"))
        return {"out": sep.join(_fmt(x) for x in items)}


def _fmt(x) -> str:
    """Аккуратное строковое представление элемента (целые без .0)."""
    if isinstance(x, float) and abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return str(x)
