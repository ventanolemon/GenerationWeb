"""
Узлы управления потоком (категория control).

Ветвление в чистом dataflow-DAG реализовано как «жадный» мультиплексор:
обе ветви входят в select как обычные значения (исполнитель вычисляет их в
топопорядке), а select по булеву условию возвращает одну из них. Это не требует
переписывания исполнителя — узлы остаются обычными вершинами DAG.

Узлы:
  compare       — NUMBER op NUMBER -> BOOL (==, !=, <, <=, >, >=);
  number_check  — NUMBER -> BOOL (even/odd/positive/negative/divisible_by);
  select        — BOOL + on_true:T + on_false:T -> T (тип T параметризуется);
  guard         — BOOL -> отбраковка (rejection sampling): cond ложно → retry.

Источник BOOL — constant_bool — живёт в sources (категория source), рядом с
константами числа/строки.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class GuardNode(Node):
    """
    Сторож: отбраковка кандидата по булеву условию (rejection sampling).

    Вход cond (BOOL) проверяется; если он не совпал с ожидаемым (mode), узел
    бросает RetryGeneration — весь граф пересобирается с новыми случайными
    значениями (whole-graph retry). Так выражается «генерируй, пока не выполнено
    условие»: дискриминант не полный квадрат, dx/dt≠0, корень рационален и т.п.

    Необязательный вход value (любой тип) проходит насквозь на выход out — чтобы
    guard можно было вставить в середину конвейера, не разрывая поток данных.
    mode: require_true (по умолчанию — оставить, если cond истинно) или
    require_false (оставить, если cond ложно — удобно «отвергнуть, если …»).
    """
    type_id = "guard"
    category = "control"
    display_name = "Сторож (проверка)"
    description = ("Отбраковать кандидата по условию: если cond не выполнен — "
                   "перегенерация графа. value (любой тип) проходит насквозь. "
                   "Вход: cond (BOOL), value. Выход: value.")
    INPUTS = [
        Port("cond", PortType.BOOL),
        Port("value", PortType.ANY, required=False),
    ]
    OUTPUTS = [Port("out", PortType.ANY)]
    PARAMS_SCHEMA = {
        "mode": {"type": "enum", "values": ["require_true", "require_false"],
                 "default": "require_true"},
    }

    def compute(self, inputs, ctx: ExecContext):
        cond = bool(inputs.get("cond"))
        want = self.params.get("mode", "require_true") == "require_true"
        if cond != want:
            raise RetryGeneration(
                f"{self.node_ref()}: условие не выполнено (cond={cond})."
            )
        return {"out": inputs.get("value")}


# Операторы сравнения. Имя → функция от (a, b).
_COMPARE_OPS = {
    "==": lambda a, b: abs(a - b) < 1e-9,
    "!=": lambda a, b: abs(a - b) >= 1e-9,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class CompareNode(Node):
    """
    Сравнить два числа, вернуть BOOL.

    Правый операнд — вход b либо (если не подключён) параметр b: сравнение
    с константой не требует отдельного узла-числа.

    Сам ОПЕРАТОР тоже бывает входом. Понадобилось на старом задании по
    информатике «сколько раз программа выведет YES»: знак сравнения там
    выбирается случайно, то есть он данные, а не настройка узла. Обойти
    это нечем — четыре узла с фиксированными знаками пришлось бы
    выбирать мультиплексором, а `pick` булевы каналы не берёт вовсе.

    Провод главнее параметра, как у весов случайного выбора и у
    начального значения регистра: параметр остаётся значением по
    умолчанию, а не спорит с проводом.
    """
    type_id = "compare"
    category = "control"
    display_name = "Сравнение"
    INPUTS = [Port("a", PortType.NUMBER),
              Port("b", PortType.NUMBER, required=False),
              Port("op", PortType.STRING, required=False)]
    OUTPUTS = [Port("out", PortType.BOOL)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": list(_COMPARE_OPS), "default": "=="},
        "b": {"type": "number", "default": 0, "optional": True},
    }

    def validate_params(self) -> None:
        op = self.params.get("op", "==")
        if op not in _COMPARE_OPS:
            raise GraphValidationError(
                f"{self.node_ref()}: неизвестный оператор {op!r}. "
                f"Допустимы: {list(_COMPARE_OPS)}"
            )

    def compute(self, inputs, ctx: ExecContext):
        name = inputs.get("op") or self.params.get("op", "==")
        name = str(name).strip()
        if name not in _COMPARE_OPS:
            # По проводу пришёл мусор. Не молча подставляем «==»: тогда
            # задание сравнивало бы не тем знаком, и никто бы не заметил.
            raise RetryGeneration(
                f"{self.node_ref()}: оператор {name!r} неизвестен; "
                f"допустимы {', '.join(_COMPARE_OPS)}.")
        op = _COMPARE_OPS[name]
        right = inputs.get("b")
        if right is None:
            right = self.params.get("b", 0)
        try:
            right = float(right)
        except (TypeError, ValueError):
            right = 0.0
        return {"out": bool(op(float(inputs["a"]), right))}


class BoolNumberNode(Node):
    """
    Логическое значение как число: да → 1, нет → 0.

    Без него булев результат в арифметику не попадает вовсе, и «сколько
    случаев из девяти подходит» — форма, которой полна информатика и
    теория вероятностей, — собиралась мультиплексором с двумя
    константами на каждое сравнение. Четыре узла шума в теле цикла из
    двадцати одного, и все четыре не про задачу.

    Отдельный узел, а не молчаливое приведение типов: `if x` над числом
    и `if x` над логическим значением — разные вопросы, и сливать их в
    графе значило бы прятать, где именно произошло превращение.
    """
    type_id = "bool_number"
    category = "control"
    display_name = "Да/нет → число"
    description = "Логическое значение числом (1/0). Вход: BOOL. Выход: NUMBER."
    INPUTS = [Port("in", PortType.BOOL)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": 1.0 if inputs.get("in") else 0.0}


# Проверки одного числа. Имя → функция от (value, param).
_CHECKS = {
    "even":          lambda v, _p: abs(v - round(v)) < 1e-9 and round(v) % 2 == 0,
    "odd":           lambda v, _p: abs(v - round(v)) < 1e-9 and round(v) % 2 != 0,
    "positive":      lambda v, _p: v > 0,
    "negative":      lambda v, _p: v < 0,
    "integer":       lambda v, _p: abs(v - round(v)) < 1e-9,
    "divisible_by":  lambda v, p: p not in (0, None)
                                  and abs((v / p) - round(v / p)) < 1e-9,
}


class NumberCheckNode(Node):
    """Проверить число на свойство (чётность, знак, делимость), вернуть BOOL."""
    type_id = "number_check"
    category = "control"
    display_name = "Проверка числа"
    INPUTS = [Port("in", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.BOOL)]
    PARAMS_SCHEMA = {
        "check": {"type": "enum", "values": list(_CHECKS), "default": "even"},
        "divisor": {"type": "number", "default": 2, "optional": True},
    }

    def validate_params(self) -> None:
        check = self.params.get("check", "even")
        if check not in _CHECKS:
            raise GraphValidationError(
                f"{self.node_ref()}: неизвестная проверка {check!r}. "
                f"Допустимы: {list(_CHECKS)}"
            )

    def compute(self, inputs, ctx: ExecContext):
        check = self.params.get("check", "even")
        try:
            divisor = float(self.params.get("divisor", 2))
        except (TypeError, ValueError):
            divisor = 2.0
        return {"out": bool(_CHECKS[check](float(inputs["in"]), divisor))}


# Типы, между которыми умеет выбирать select (имя в UI → PortType).
_SELECT_TYPES = {
    "number": PortType.NUMBER,
    "string": PortType.STRING,
    "number_dict": PortType.NUMBER_DICT,
    "block": PortType.BLOCK,
    "block_list": PortType.BLOCK_LIST,
    "image": PortType.IMAGE,
    "task": PortType.TASK,
    "expr": PortType.EXPR,      # выбор между символьными выражениями
    "matrix": PortType.MATRIX,  # ...и матрицами
    "list": PortType.LIST,      # ...и коллекциями
}


class SelectNode(Node):
    """
    Мультиплексор: по условию вернуть on_true или on_false.

    Тип данных ветвей задаётся параметром value_type — порты on_true/on_false/out
    получают этот тип. Обе ветви вычисляются исполнителем (жадно), select лишь
    выбирает одну — это корректно для чистого dataflow без переписывания executor.
    """
    type_id = "select"
    category = "control"
    display_name = "Выбор (если)"
    PARAMS_SCHEMA = {
        "value_type": {"type": "enum", "values": list(_SELECT_TYPES),
                       "default": "number"},
    }
    TYPE_PARAM = "value_type"
    TYPE_PARAM_MAP = _SELECT_TYPES

    def validate_params(self) -> None:
        vt = self.params.get("value_type", "number")
        if vt not in _SELECT_TYPES:
            raise GraphValidationError(
                f"{self.node_ref()}: неизвестный тип ветвей {vt!r}. "
                f"Допустимы: {list(_SELECT_TYPES)}"
            )

    def _value_type(self) -> PortType:
        return _SELECT_TYPES.get(self.params.get("value_type", "number"),
                                 PortType.NUMBER)

    def input_ports(self):
        t = self._value_type()
        return [
            Port("cond", PortType.BOOL),
            Port("on_true", t),
            Port("on_false", t),
        ]

    def output_ports(self):
        return [Port("out", self._value_type())]

    def type_param_ports(self) -> set[str]:
        return {"on_true", "on_false", "out"}

    def compute(self, inputs, ctx: ExecContext):
        return {"out": inputs["on_true"] if inputs.get("cond") else inputs["on_false"]}


class PickNode(Node):
    """
    N-канальный мультиплексор: индекс выбирает один из N входов одного типа.

    Замена громоздким цепочкам select при трёх и более вариантах: категория
    ответа/структура условия задаётся числом (0..N−1), pick отдаёт in<индекс>.
    Тип каналов — value_type (как у select), число каналов — count. Все входы
    вычисляются исполнителем жадно (обычные вершины DAG), pick лишь выбирает.

    Индекс вне диапазона или неподключённый выбранный вход → RetryGeneration.
    """
    type_id = "pick"
    category = "control"
    display_name = "Выбор по индексу"
    PARAMS_SCHEMA = {
        "count": {"type": "int", "default": 3},
        "value_type": {"type": "enum", "values": list(_SELECT_TYPES),
                       "default": "block"},
    }
    TYPE_PARAM = "value_type"
    TYPE_PARAM_MAP = _SELECT_TYPES

    def validate_params(self) -> None:
        vt = self.params.get("value_type", "block")
        if vt not in _SELECT_TYPES:
            raise GraphValidationError(
                f"{self.node_ref()}: неизвестный тип каналов {vt!r}. "
                f"Допустимы: {list(_SELECT_TYPES)}"
            )
        try:
            if int(self.params.get("count", 3)) < 2:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: count должен быть целым ≥ 2."
            )

    def _count(self) -> int:
        try:
            return max(2, int(self.params.get("count", 3)))
        except (TypeError, ValueError):
            return 3

    def _value_type(self) -> PortType:
        return _SELECT_TYPES.get(self.params.get("value_type", "block"),
                                 PortType.BLOCK)

    def input_ports(self):
        t = self._value_type()
        ports = [Port("index", PortType.NUMBER)]
        ports += [Port(f"in{i}", t, required=False) for i in range(self._count())]
        return ports

    def output_ports(self):
        return [Port("out", self._value_type())]

    def type_param_ports(self) -> set[str]:
        return {f"in{i}" for i in range(self._count())} | {"out"}

    def compute(self, inputs, ctx: ExecContext):
        try:
            i = int(round(float(inputs.get("index", 0))))
        except (TypeError, ValueError):
            raise RetryGeneration(
                f"{self.node_ref()}: индекс не число ({inputs.get('index')!r})."
            )
        if not 0 <= i < self._count():
            raise RetryGeneration(
                f"{self.node_ref()}: индекс {i} вне диапазона "
                f"[0; {self._count()})."
            )
        value = inputs.get(f"in{i}")
        if value is None:
            raise RetryGeneration(
                f"{self.node_ref()}: выбранный вход in{i} не подключён."
            )
        return {"out": value}
