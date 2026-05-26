"""
Композитные генераторы. GroupGenerator и TestGenerator. Без изменений.
"""

from __future__ import annotations
import random
from typing import List, Tuple

from .blocks import TextBlock
from .generator import Capability, TaskGenerator
from .task import StaticTask


class GroupGenerator(TaskGenerator):
    capabilities = Capability.STATIC | Capability.EXPORTABLE | Capability.GROUPABLE

    def __init__(self, name: str, children: List[TaskGenerator],
                 partition_id: int | None = None):
        self.name = name
        self.partition_id = partition_id
        self.children = [c for c in children
                         if Capability.GROUPABLE in c.capabilities]
        if not self.children:
            raise ValueError(
                "В группу не попал ни один групповой генератор. "
                "Возможно, все дети — INTERACTIVE."
            )

    def generate(self) -> StaticTask:
        chosen = random.choice(self.children)
        task = chosen.generate()
        if isinstance(task, StaticTask):
            task.meta = {**task.meta, "child_partition": chosen.partition_id}
            return task
        raise TypeError(
            f"Ребёнок {chosen.name!r} вернул не StaticTask, "
            "хотя имел флаг GROUPABLE."
        )


class TestGenerator(TaskGenerator):
    capabilities = Capability.STATIC | Capability.EXPORTABLE

    def __init__(self, name: str, items: List[Tuple[TaskGenerator, int]],
                 partition_id: int | None = None):
        self.name = name
        self.partition_id = partition_id
        for gen, _ in items:
            if Capability.GROUPABLE not in gen.capabilities:
                raise ValueError(
                    f"Генератор {gen.name!r} нельзя положить в тест — "
                    "у него нет флага GROUPABLE."
                )
        self.items = items

    def generate(self) -> StaticTask:
        statement: list = []
        answer: list = []
        n = 1
        for gen, count in self.items:
            for _ in range(count):
                t = gen.generate()
                if not isinstance(t, StaticTask):
                    continue
                statement.append(TextBlock(f"{n}. "))
                statement.extend(t.statement)
                statement.append(TextBlock(""))
                answer.append(TextBlock(f"{n}. "))
                answer.extend(t.answer)
                answer.append(TextBlock(""))
                n += 1
        return StaticTask(
            statement=statement,
            answer=answer,
            meta={"is_test": True, "task_count": n - 1},
        )
