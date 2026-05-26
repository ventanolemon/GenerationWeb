"""
Block — атомарная единица контента в задании или ответе.

Контракт: каждый блок умеет рендериться в четырёх средах.
Чтобы добавить новый тип контента (например, граф), нужно создать
класс, наследующий Block, и реализовать четыре метода. Все существующие
View, экспортёры и веб-сериализаторы подхватят его автоматически.

Веб-сериализация (to_dict) идёт через тот же полиморфный механизм, что
и render_qt / render_plain / render_docx. Это значит, что добавление
нового блока не требует правки FastAPI-сервиса или фронта — фронт
рендерит блоки по полю "type" из словаря.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget
    from docx.document import Document as DocxDoc


class Block(ABC):
    """Базовый класс единицы контента."""

    @abstractmethod
    def render_qt(self, parent: "QWidget") -> "QWidget":
        """Создать виджет PyQt для отображения в десктоп-интерфейсе."""

    @abstractmethod
    def render_plain(self) -> str:
        """Текстовое представление: буфер обмена, отладка, простой текст."""

    @abstractmethod
    def render_docx(self, doc: "DocxDoc") -> None:
        """Дописать себя в открытый docx-документ при экспорте."""

    @abstractmethod
    def to_dict(self) -> dict:
        """JSON-сериализуемое представление блока для веб-API.

        Каждый подкласс возвращает {"type": "<имя>", ...поля}. Поле "type"
        диктует, какой компонент фронта будет рендерить блок. Бинарные
        данные (изображения, рендеры формул) кодируются в base64 строкой
        в поле "image_b64". Если что-то отрендерить не удалось — поле
        выставляется в None, но "type" и текстовые поля сохраняются,
        чтобы фронт мог дать фолбэк.
        """
