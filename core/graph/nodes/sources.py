"""
Узлы-источники: производят значения, не имея входов.

random_natural / random_real переиспользуют движок физики как тело:
VariableSpec + generation.generate_value. Никакой новой логики генерации.
"""

from __future__ import annotations

from exercises.fisic.generation import generate_value, parse_variable_spec

from ..errors import GraphValidationError
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class ConstantNumberNode(Node):
    """Литерал-число."""
    type_id = "constant_number"
    category = "source"
    display_name = "Константа (число)"
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {"value": {"type": "number", "default": 0}}

    def validate_params(self) -> None:
        try:
            float(self.params.get("value", 0))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'value' должен быть числом."
            )

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(self.params.get("value", 0))}


class ConstantStringNode(Node):
    """Литерал-строка."""
    type_id = "constant_string"
    category = "source"
    display_name = "Константа (строка)"
    OUTPUTS = [Port("out", PortType.STRING)]
    PARAMS_SCHEMA = {"value": {"type": "string", "default": ""}}

    def compute(self, inputs, ctx: ExecContext):
        return {"out": str(self.params.get("value", ""))}


class ConstantBoolNode(Node):
    """Литерал-истинность (источник BOOL)."""
    type_id = "constant_bool"
    category = "source"
    display_name = "Константа (да/нет)"
    OUTPUTS = [Port("out", PortType.BOOL)]
    PARAMS_SCHEMA = {
        "value": {"type": "enum", "values": ["true", "false"], "default": "true"},
    }

    def compute(self, inputs, ctx: ExecContext):
        return {"out": str(self.params.get("value", "true")).lower() == "true"}


class _RandomVarNode(Node):
    """Общая база для случайных источников. KIND задаёт тип значения."""
    KIND = "real"
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def _spec(self):
        # parse_variable_spec нормализует строки/формулы в min/max/step/forbidden.
        cfg = {**self.params, "kind": self.KIND}
        return parse_variable_spec(self.node_id, cfg)

    def validate_params(self) -> None:
        try:
            self._spec()
        except Exception as e:                       # ValueError из VariableSpec
            raise GraphValidationError(
                f"Узел {self.node_id!r}: некорректные параметры — {e}"
            )

    def compute(self, inputs, ctx: ExecContext):
        return {"out": generate_value(self._spec())}


class RandomNaturalNode(_RandomVarNode):
    """Случайное натуральное число (≥1)."""
    type_id = "random_natural"
    category = "source"
    display_name = "Случайное натуральное"
    KIND = "natural"
    PARAMS_SCHEMA = {
        "min": {"type": "number", "default": 1},
        "max": {"type": "number", "default": 10},
        "step": {"type": "number", "default": 1, "optional": True},
        "forbidden": {"type": "list", "default": [], "optional": True},
    }


class RandomRealNode(_RandomVarNode):
    """Случайное вещественное число."""
    type_id = "random_real"
    category = "source"
    display_name = "Случайное вещественное"
    KIND = "real"
    PARAMS_SCHEMA = {
        "min": {"type": "number", "default": 0},
        "max": {"type": "number", "default": 1},
        "decimals": {"type": "int", "default": 2, "optional": True},
        "step": {"type": "number", "optional": True},
        "forbidden": {"type": "list", "default": [], "optional": True},
    }


class StringListNode(Node):
    """Список строк-литералов (например, набор слов). Источник LIST."""
    type_id = "string_list"
    category = "source"
    display_name = "Список строк"
    OUTPUTS = [Port("out", PortType.LIST)]
    PARAMS_SCHEMA = {"items": {"type": "list", "default": []}}

    def compute(self, inputs, ctx: ExecContext):
        return {"out": [str(x) for x in (self.params.get("items") or [])]}


class NumberRangeNode(Node):
    """Диапазон чисел [start; stop] с шагом step. Источник LIST чисел."""
    type_id = "number_range"
    category = "source"
    display_name = "Диапазон чисел"
    OUTPUTS = [Port("out", PortType.LIST)]
    PARAMS_SCHEMA = {
        "start": {"type": "number", "default": 1},
        "stop": {"type": "number", "default": 5},
        "step": {"type": "number", "default": 1, "optional": True},
    }

    _CAP = 10_000

    def compute(self, inputs, ctx: ExecContext):
        start = float(self.params.get("start", 1))
        stop = float(self.params.get("stop", 5))
        step = float(self.params.get("step", 1) or 1)
        if step == 0:
            step = 1.0
        out: list[float] = []
        v = start
        # Включительно по stop, с защитой по числу элементов.
        while (step > 0 and v <= stop + 1e-9) or (step < 0 and v >= stop - 1e-9):
            out.append(round(v, 9))
            if len(out) >= self._CAP:
                break
            v += step
        return {"out": out}
