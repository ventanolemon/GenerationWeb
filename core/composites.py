"""
Композитные генераторы.

GroupGenerator — выбирает случайного из своих детей при каждом generate().
TestGenerator — собирает один большой StaticTask из заданий нескольких генераторов
                с указанным количеством каждого.

Оба сами реализуют TaskGenerator и не знают о предметах своих детей.
Английский (INTERACTIVE) физически не попадает в группы/тесты благодаря
фильтру по GROUPABLE.
"""

from __future__ import annotations
import random
from typing import List, Tuple

from .blocks import TextBlock
from .generator import Capability, TaskGenerator
from .task import StaticTask


class GroupGenerator(TaskGenerator):
    """Группа: при каждом generate() выбирается один случайный ребёнок."""

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
        # Прокидываем мету ребёнка наверх, чтобы знать, кто сгенерировал
        if isinstance(task, StaticTask):
            task.meta = {**task.meta, "child_partition": chosen.partition_id}
            return task
        # Сюда не должны попадать благодаря фильтру в __init__
        raise TypeError(
            f"Ребёнок {chosen.name!r} вернул не StaticTask, "
            "хотя имел флаг GROUPABLE."
        )


class TestGenerator(TaskGenerator):
    """
    Тест: собирает один StaticTask со списком заданий, пронумерованных по порядку.

    items = [(generator, count), ...] — каждый генератор вызывается count раз.
    """

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
                statement.append(TextBlock(""))   # отбивка
                answer.append(TextBlock(f"{n}. "))
                answer.extend(t.answer)
                answer.append(TextBlock(""))
                n += 1
        return StaticTask(
            statement=statement,
            answer=answer,
            meta={"is_test": True, "task_count": n - 1},
        )
