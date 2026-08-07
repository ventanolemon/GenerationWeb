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

from ..errors import GraphValidationError, RetryGeneration
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


def _coerce_to_elem_type(value, elem_type: str):
    """
    Привести литеральное значение (из текстового поля items) к elem_type.

    Общая для list_new и random_choice: раньше list_new в режиме items её не
    вызывал вовсе и молча хранил голые Python-строки даже при elem_type=expr/
    matrix — узел, стоящий следом, "угадывал" тип сам (большинство EXPR-
    потребителей вызывают as_expr на своих входах), но это везло не всегда
    (list_length/list_join элемент не трогают, а сравнение по isinstance —
    свежий sympy.Basic vs str — уже нет). Здесь элемент приводится к
    настоящему значению заявленного типа сразу при создании списка.
    """
    if elem_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise RetryGeneration(f"элемент {value!r} не число.")
    if elem_type == "string":
        return _fmt(value) if isinstance(value, (int, float)) else str(value)
    if elem_type == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "да", "yes")
        return bool(value)
    if elem_type == "expr":
        from ..symbolic import as_expr
        return as_expr(value)
    if elem_type == "matrix":
        from ..symbolic import as_matrix
        return as_matrix(value)
    return value      # block — как есть


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
    TYPE_PARAM = "elem_type"
    TYPE_PARAM_MAP = _ELEM_TYPES

    def _count(self) -> int:
        try:
            return max(0, int(self.params.get("count", 0)))
        except (TypeError, ValueError):
            return 0

    def input_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port(f"in{i}", et, required=False) for i in range(self._count())]

    def type_param_ports(self) -> set[str]:
        return {f"in{i}" for i in range(self._count())}

    def compute(self, inputs, ctx: ExecContext):
        if self._count() > 0:
            return {"out": [inputs[f"in{i}"] for i in range(self._count())
                            if f"in{i}" in inputs]}
        # Иначе — из текстовых items, приведённых к elem_type (числа/bool/
        # expr/matrix разбираются по-настоящему, не остаются голым текстом).
        et = str(self.params.get("elem_type", "number"))
        return {"out": [_coerce_to_elem_type(raw, et)
                        for raw in (self.params.get("items") or [])]}


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
    TYPE_PARAM = "elem_type"
    TYPE_PARAM_MAP = _ELEM_TYPES

    def input_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port("list", PortType.LIST, required=False), Port("item", et)]

    def type_param_ports(self) -> set[str]:
        return {"item"}

    def compute(self, inputs, ctx: ExecContext):
        base = _as_list(inputs.get("list"))
        base.append(inputs.get("item"))
        return {"out": base}


class ListConcatNode(Node):
    """Склеить два списка в один (LIST + LIST → LIST). Например, две ветви
    корней уравнения перед изображением на плоскости."""
    type_id = "list_concat"
    category = "list"
    display_name = "Объединить списки"
    description = ("Соединить списки a и b в один (a затем b). "
                   "Вход: LIST, LIST. Выход: LIST.")
    INPUTS = [Port("a", PortType.LIST), Port("b", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.LIST)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": _as_list(inputs.get("a")) + _as_list(inputs.get("b"))}


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
    TYPE_PARAM = "elem_type"
    TYPE_PARAM_MAP = _ELEM_TYPES

    def output_ports(self):
        et = _ELEM_TYPES.get(self.params.get("elem_type", "number"), PortType.NUMBER)
        return [Port("out", et)]

    def type_param_ports(self) -> set[str]:
        return {"out"}

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
    Случайный выбор элемента(ов) из набора — «пул вариантов» одним узлом.

    Набор берётся из входа list (LIST), а если он не подключён — из параметра
    items (текстовые литералы). Каждый выбранный элемент приводится к типу
    elem_type (number/string/expr/matrix/bool/block), поэтому результат можно
    сразу подать дальше: строку — в маркер #имя# текста, выражение — в diff/limit
    и т.п. Воспроизводимо через ctx.rng (как random_natural).

    Параметр count — сколько элементов выбрать (по умолчанию 1). При count=1
    выход типизирован как elem_type (как раньше — обратная совместимость,
    подключается прямо в узлы соответствующего типа). При count>1 выход — LIST
    (обычная связка с list_get/list_join/map или циклом). allow_duplicates
    (по умолчанию False) — можно ли выбрать один и тот же элемент дважды: False
    — выборка БЕЗ повторов (ctx.rng.sample, count не может превышать размер
    набора), True — выборка С повторами (ctx.rng.choices).

    Покрывает самый частый паттерн реальных генераторов (пулы эквивалентностей,
    варианты функций) без связки list_new + random_natural + list_get.
    """
    type_id = "random_choice"
    category = "source"
    display_name = "Случайный выбор"
    description = ("Случайно выбрать count элементов из набора (вход LIST или "
                   "параметр items). Тип выхода — elem_type при count=1, иначе "
                   "LIST. allow_duplicates — допустимы ли повторы.")
    INPUTS = [Port("list", PortType.LIST, required=False),
              # Веса приходят проводом ИЛИ параметром. Провод нужен, чтобы
              # несколько выборов можно было сделать зависимыми от одного
              # параметра генерации: посчитал веса один раз — раздал.
              Port("weights", PortType.LIST, required=False)]
    PARAMS_SCHEMA = {
        "elem_type": {"type": "enum", "values": list(_ELEM_TYPES),
                      "default": "string", "optional": True},
        "items": {"type": "list", "default": [], "optional": True},
        "weights": {"type": "list", "default": [], "optional": True},
        "count": {"type": "int", "default": 1, "optional": True},
        "allow_duplicates": {"type": "bool", "default": False, "optional": True},
    }
    TYPE_PARAM = "elem_type"
    TYPE_PARAM_MAP = _ELEM_TYPES

    def type_param_ports(self) -> set[str]:
        return {"out"} if self._count() == 1 else set()

    def summary(self) -> str:
        pool = len(self.params.get("items") or [])
        src = f"из {pool}" if pool else "из списка"
        n = self._count()
        head = f"{n} {src}" if n > 1 else src
        return head + " ⚖" if (self.params.get("weights") or []) else head

    def _count(self) -> int:
        try:
            return max(1, int(self.params.get("count", 1)))
        except (TypeError, ValueError):
            return 1

    def validate_params(self) -> None:
        if self._count() != int(self.params.get("count", 1) or 1):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: count должно быть целым ≥ 1."
            )
        items = self.params.get("items") or []
        allow_dup = bool(self.params.get("allow_duplicates", False))
        # Статические items известны заранее — проверяем размер сразу; набор
        # из входа list известен только в рантайме (см. compute).
        if items and not allow_dup and self._count() > len(items):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: count={self._count()} больше набора "
                f"({len(items)}) без повторов (allow_duplicates=false)."
            )
        weights = self.params.get("weights") or []
        if weights:
            self._parse_weights(weights, len(items) if items else len(weights))

    def output_ports(self):
        if self._count() == 1:
            et = _ELEM_TYPES.get(self.params.get("elem_type", "string"), PortType.STRING)
            return [Port("out", et)]
        return [Port("out", PortType.LIST)]

    def _coerce(self, value):
        try:
            return _coerce_to_elem_type(value, self.params.get("elem_type", "string"))
        except RetryGeneration:
            raise RetryGeneration(
                f"random_choice {self.node_id!r}: элемент {value!r} не число."
            )

    def _parse_weights(self, raw, expected: int) -> list[float]:
        """
        Разобрать и проверить веса.

        Сумма НЕ обязана быть единицей — узел нормирует сам. Требовать
        долей значило бы заставлять автора подгонять их вручную при каждом
        добавлении варианта, а это ровно та арифметика, которую машина
        делает лучше.
        """
        values = []
        for item in raw:
            try:
                values.append(float(str(item).replace(",", ".")))
            except (TypeError, ValueError):
                raise GraphValidationError(
                    f"Узел {self.node_id!r}: вес {item!r} — не число.")
        if len(values) != expected:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: весов {len(values)}, "
                f"а вариантов {expected} — они сопоставляются по порядку.")
        if any(v < 0 for v in values):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: отрицательный вес.")
        if sum(values) <= 0:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: все веса нулевые — выбирать не из чего.")
        return values

    def _weights_for(self, items, inputs) -> "list[float] | None":
        raw = _as_list(inputs.get("weights")) or (self.params.get("weights") or [])
        if not raw:
            return None
        return self._parse_weights(raw, len(items))

    def compute(self, inputs, ctx: ExecContext):
        items = _as_list(inputs.get("list"))
        if not items:
            items = list(self.params.get("items") or [])
        if not items:
            raise RetryGeneration(
                f"random_choice {self.node_id!r}: пустой набор для выбора."
            )
        count = self._count()
        allow_dup = bool(self.params.get("allow_duplicates", False))
        weights = self._weights_for(items, inputs)

        if allow_dup:
            chosen = ctx.rng.choices(items, weights=weights, k=count)
        else:
            if count > len(items):
                raise RetryGeneration(
                    f"random_choice {self.node_id!r}: count={count} больше "
                    f"набора ({len(items)}) без повторов."
                )
            if weights is None:
                chosen = ctx.rng.sample(items, count)
            else:
                # Взвешенная выборка БЕЗ возвращения: выбранный вариант
                # убирается, и распределение на следующем шаге считается
                # заново по остатку. Другого «правильного» смысла у весов
                # без повторов нет — но стоит знать, что вес означает
                # шанс на ПЕРВОМ шаге, а не долю в итоговой выборке.
                pool = list(items)
                pool_weights = list(weights)
                chosen = []
                for _ in range(count):
                    picked = ctx.rng.choices(pool, weights=pool_weights, k=1)[0]
                    index = pool.index(picked)
                    pool.pop(index)
                    pool_weights.pop(index)
                    chosen.append(picked)
        coerced = [self._coerce(v) for v in chosen]
        return {"out": coerced[0] if count == 1 else coerced}


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
