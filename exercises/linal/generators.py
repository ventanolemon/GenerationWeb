"""
Адаптеры модулей линейной алгебры.

Оригинальные функции get_exercise() в ex2_d.py и ex3_d.py не меняются.
Здесь только обёртки, оборачивающие их результат в StaticTask.
"""

from __future__ import annotations

from core import TaskGenerator, StaticTask, TextBlock, Capability, STATIC_DEFAULT
from . import ex2_d, ex3_d


def _wrap_text_pair(task_text: str, answer_text: str) -> StaticTask:
    """
    Линал возвращает кортеж из двух строк. Превращаем их в StaticTask
    с одним TextBlock на условие и одним — на ответ.
    """
    return StaticTask(
        statement=[TextBlock(task_text)],
        answer=[TextBlock(answer_text)],
    )


class Linal2DGenerator(TaskGenerator):
    """Задания на 2D-плоскость (треугольники, прямые)."""

    name = "Задания на 2D плоскость"
    partition_id = 1
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        text, answer = ex2_d.get_exercise()
        return _wrap_text_pair(text, answer)


class Linal3DGenerator(TaskGenerator):
    """Задания на 3D-плоскость."""

    name = "Задания на 3D плоскость"
    partition_id = 4
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        text, answer = ex3_d.get_exercise()
        return _wrap_text_pair(text, answer)


def all_generators() -> list[TaskGenerator]:
    """Все генераторы модуля. Используется при регистрации."""
    return [Linal2DGenerator(), Linal3DGenerator()]
