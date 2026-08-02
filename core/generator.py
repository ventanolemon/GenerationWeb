"""
TaskGenerator — контракт модуля.

Модуль = один класс, наследующий TaskGenerator, с методом generate().
Декларирует свои возможности через флаги Capability — каркас опирается
на них при выборе представления и при включении в группы/тесты.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Flag, auto

from .task import Task


class Capability(Flag):
    """Флаги возможностей генератора."""
    NONE = 0

    STATIC      = auto()  # generate() возвращает StaticTask
    INTERACTIVE = auto()  # generate() возвращает InteractiveTask

    EXPORTABLE  = auto()  # имеет смысл выводить в .docx
    GROUPABLE   = auto()  # можно положить в группу или тест
    HAS_IMAGES  = auto()  # подсказка для UI: задание содержит ImageBlock


# Удобные дефолтные наборы
STATIC_DEFAULT = Capability.STATIC | Capability.GROUPABLE | Capability.EXPORTABLE


class TaskGenerator(ABC):
    """
    Контракт модуля. Один файл — один класс, наследующий это.

    Обязательно:
      * атрибут name (человекочитаемое имя)
      * метод generate() → Task
      * капабилити, согласованные с типом возврата

    Опционально:
      * partition_id — связь с записью в БД
      * configure(params) — применение параметров из БД
    """

    name: str = ""
    partition_id: int | None = None
    capabilities: Capability = STATIC_DEFAULT

    @abstractmethod
    def generate(self) -> Task:
        """Сгенерировать новое задание."""

    def configure(self, params: dict) -> None:
        """
        Применить параметры из БД (поле generation_parametrs).
        Дефолтная реализация — игнорировать.
        """
        return None
