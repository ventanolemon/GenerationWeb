"""
Узлы сборки задания.

block_list  — аккумулятор: N входов-блоков → list[Block].
static_task — финал пайплайна: StaticTask(statement=..., answer=...).

StaticTask из core.task — чистый dataclass (без Qt), поэтому импортируется
на верхнем уровне. Блоки внутри списков могут быть любыми объектами Block.
"""

from __future__ import annotations

from core.task import StaticTask

from ..errors import GraphValidationError
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class BlockListNode(Node):
    """Собрать несколько блоков в список (в порядке in0, in1, ...)."""
    type_id = "block_list"
    category = "assembly"
    display_name = "Список блоков"
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {"count": {"type": "int", "default": 1}}

    def _count(self) -> int:
        try:
            return max(1, int(self.params.get("count", 1)))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'count' должен быть целым ≥ 1."
            )

    def validate_params(self) -> None:
        self._count()

    def input_ports(self):
        return [Port(f"in{i}", PortType.BLOCK, required=False)
                for i in range(self._count())]

    def compute(self, inputs, ctx: ExecContext):
        out = []
        for i in range(self._count()):
            value = inputs.get(f"in{i}")
            if value is not None:
                out.append(value)
        return {"out": out}


class StaticTaskNode(Node):
    """Финал: собрать StaticTask из списков блоков условия и ответа."""
    type_id = "static_task"
    category = "assembly"
    display_name = "Статическое задание"
    INPUTS = [
        Port("statement", PortType.BLOCK_LIST),
        Port("answer", PortType.BLOCK_LIST),
    ]
    OUTPUTS = [Port("out", PortType.TASK)]

    def compute(self, inputs, ctx: ExecContext):
        statement = inputs.get("statement") or []
        answer = inputs.get("answer") or []
        if not isinstance(statement, list):
            statement = [statement]
        if not isinstance(answer, list):
            answer = [answer]
        return {"out": StaticTask(
            statement=list(statement),
            answer=list(answer),
            meta={"source": "graph"},
        )}
