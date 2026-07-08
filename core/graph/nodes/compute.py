"""
Узлы вычисления — самая богатая категория. Тела — чистые функции движка физики.

var_dict   — коллектор именованных значений → NUMBER_DICT.
formula    — обёртка над expression.evaluate_formula (безопасный AST, без eval).
constraint — ResultConstraint.check/.normalize; при отказе → RetryGeneration.
template   — подстановка #имя# (как fisic_generater._build_task).
"""

from __future__ import annotations
import math
import re

from exercises.fisic.constraints import ResultConstraint
from exercises.fisic.expression import (
    FormulaError, evaluate_formula, extract_variable_names, parse_formula,
)
from exercises.fisic.formatting import format_number

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class VarDictNode(Node):
    """Собрать N именованных чисел в словарь dict[str, float]."""
    type_id = "var_dict"
    category = "compute"
    display_name = "Словарь переменных"
    OUTPUTS = [Port("out", PortType.NUMBER_DICT)]
    PARAMS_SCHEMA = {"names": {"type": "list", "default": []}}

    def validate_params(self) -> None:
        names = self.params.get("names")
        if not isinstance(names, list) or not names:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'names' должен быть непустым списком имён."
            )
        if len(set(names)) != len(names):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: имена переменных не уникальны."
            )

    def input_ports(self):
        return [Port(str(n), PortType.NUMBER) for n in self.params["names"]]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": {str(n): float(inputs[str(n)]) for n in self.params["names"]}}


class FormulaNode(Node):
    """
    Вычислить формулу. Входы-числа создаются автоматически по именам переменных
    в самой формуле — отдельный var_dict больше не нужен. Например, формула
    'a+b' даёт два входа a и b. Запасной вход vars (NUMBER_DICT) тоже принимается
    (для совместимости и динамических наборов).
    """
    type_id = "formula"
    category = "compute"
    display_name = "Формула"
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {"expr": {"type": "string", "default": ""}}

    def validate_params(self) -> None:
        expr = self.params.get("expr")
        if not expr:
            raise GraphValidationError(f"Узел {self.node_id!r}: пустая формула.")
        try:
            parse_formula(expr)
        except FormulaError as e:
            raise GraphValidationError(f"Узел {self.node_id!r}: ошибка формулы — {e}")

    def required_names(self) -> set[str]:
        """Имена переменных, нужные формуле (для подсказок редактора/портов)."""
        try:
            return extract_variable_names(self.params.get("expr", ""))
        except Exception:
            return set()

    def input_ports(self):
        # По одному числовому входу на каждую переменную формулы + запасной vars.
        ports = [Port(n, PortType.NUMBER, required=False)
                 for n in sorted(self.required_names())]
        ports.append(Port("vars", PortType.NUMBER_DICT, required=False))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        # Словарь переменных: из vars + из именованных входов (последние важнее).
        variables = dict(inputs.get("vars") or {})
        for n in self.required_names():
            if n in inputs and inputs[n] is not None:
                variables[n] = inputs[n]
        try:
            value = evaluate_formula(self.params["expr"], variables)
        except (OverflowError, ValueError, ZeroDivisionError) as e:
            # Числовая ошибка — как `continue` в fisic_generater.generate_task.
            raise RetryGeneration(f"Формула {self.node_id!r}: {e}")
        if math.isinf(value) or math.isnan(value):
            raise RetryGeneration(f"Формула {self.node_id!r}: результат inf/nan.")
        return {"out": float(value)}


class ConstraintNode(Node):
    """Проверка результата. Пропускает значение или просит пере-генерацию."""
    type_id = "constraint"
    category = "compute"
    display_name = "Проверка результата"
    INPUTS = [Port("in", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {
        "kind": {"type": "enum", "values": ["real", "natural", "integer"], "default": "real"},
        "min": {"type": "number", "optional": True},
        "max": {"type": "number", "optional": True},
        "tolerance": {"type": "number", "default": 1e-9, "optional": True},
    }

    def validate_params(self) -> None:
        try:
            self._constraint()
        except Exception as e:
            raise GraphValidationError(f"Узел {self.node_id!r}: {e}")

    def _constraint(self) -> ResultConstraint:
        return ResultConstraint.parse(self.params or None)

    def compute(self, inputs, ctx: ExecContext):
        rc = self._constraint()
        value = inputs["in"]
        if not rc.check(value):
            raise RetryGeneration(
                f"Проверка {self.node_id!r}: {value} не прошло (kind={rc.kind})."
            )
        return {"out": rc.normalize(value)}


_MARKER_RE = re.compile(r"#([^#\s]+)#")


def _format_value(value) -> str:
    """Аккуратное строковое представление: целые — без научной нотации."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(v - round(v)) < 1e-9:
        return format_number(v, scientific_threshold_high=float("inf"))
    return format_number(v)


def _join_prefix(prefix: str, body: str, relation: str = "=") -> str:
    """
    Приписать префикс к выражению/строке с разумной связкой.

    Связка relation (по умолчанию '=') вставляется между префиксом и телом —
    НО не дублируется, если префикс уже кончается знаком отношения/двоеточием
    ('y\\' =' → 'y\\' = …', а не 'y\\' = = …'). relation='' (или пустой
    префикс) — без связки, просто 'prefix body'. Так prefix перестаёт навязывать
    лишний '='.
    """
    prefix = str(prefix or "").strip()
    if not prefix:
        return body
    rel = str(relation or "").strip()
    if not rel or prefix[-1] in "=:<>≈≤≥≠":
        return f"{prefix} {body}"
    return f"{prefix} {rel} {body}"


def _marker_str(value) -> str:
    """
    Строковое представление значения маркера #имя# — полиморфно по типу:
    число → аккуратно (целые без .0), bool → да/нет, sympy-выражение/матрица →
    математическая запись (** → ^), строка и прочее → как есть. Позволяет
    подставлять в текст не только числа, но и выбранные строки/выражения.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        return _format_value(value)
    if type(value).__module__.split(".")[0] == "sympy":
        return str(value).replace("**", "^")
    return str(value)


def _fill_template(text: str, inputs: dict) -> str:
    """Подставить #имя# из именованных входов и из словаря vars (любой тип)."""
    variables = dict(inputs.get("vars") or {})
    for name in _marker_names(text):
        if name in inputs and inputs[name] is not None:
            variables[name] = inputs[name]
    out = str(text)
    for name, value in variables.items():
        out = out.replace(f"#{name}#", _marker_str(value))
    return out


def _marker_names(text: str) -> list[str]:
    seen, out = set(), []
    for m in _MARKER_RE.findall(str(text or "")):
        if m not in seen:
            seen.add(m); out.append(m)
    return out


class TemplateNode(Node):
    """
    Текст с подстановкой #имя#. Входы-числа создаются автоматически по маркерам
    в тексте (отдельный var_dict не нужен). Например, текст '#a# + #b#' даёт
    входы a и b. Запасной вход vars (NUMBER_DICT) тоже принимается.
    """
    type_id = "template"
    category = "compute"
    display_name = "Текстовый шаблон"
    OUTPUTS = [Port("out", PortType.STRING)]
    PARAMS_SCHEMA = {"text": {"type": "text", "default": ""}}

    def input_ports(self):
        # Маркеры — полиморфные входы (ANY): принимают число, строку, выражение.
        ports = [Port(n, PortType.ANY, required=False)
                 for n in _marker_names(self.params.get("text", ""))]
        ports.append(Port("vars", PortType.NUMBER_DICT, required=False))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        return {"out": _fill_template(self.params.get("text", ""), inputs)}

    @staticmethod
    def _format(value) -> str:
        return _marker_str(value)
