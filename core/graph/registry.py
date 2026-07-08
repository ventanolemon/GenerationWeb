"""
NodeRegistry — реестр типов узлов (калька с core.GeneratorRegistry).

Палитра визуального редактора строится из этого реестра: зарегистрировал
класс узла — он автоматически появился в UI. Тот же приём, что уже работает
для Block (добавил класс — все View его поддерживают) и для TaskGenerator.
"""

from __future__ import annotations
from typing import Iterator, Type

from .errors import GraphValidationError
from .node import Node


class NodeRegistry:
    """Хранилище классов узлов с поиском по type_id."""

    def __init__(self) -> None:
        self._classes: dict[str, Type[Node]] = {}

    def register(self, cls: Type[Node]) -> Type[Node]:
        """Зарегистрировать класс узла. Возвращает его же (удобно как декоратор)."""
        if not cls.type_id:
            raise ValueError(f"Узел {cls.__name__} не имеет type_id.")
        if cls.type_id in self._classes:
            raise ValueError(f"type_id {cls.type_id!r} уже зарегистрирован.")
        self._classes[cls.type_id] = cls
        return cls

    def get(self, type_id: str) -> Type[Node]:
        try:
            return self._classes[type_id]
        except KeyError:
            raise GraphValidationError(
                f"Неизвестный тип узла: {type_id!r}. "
                f"Доступны: {sorted(self._classes)}"
            )

    def create(self, type_id: str, node_id: str, params: dict | None = None) -> Node:
        return self.get(type_id)(node_id, params)

    def has(self, type_id: str) -> bool:
        return type_id in self._classes

    def type_ids(self) -> list[str]:
        return sorted(self._classes)

    def __iter__(self) -> Iterator[Type[Node]]:
        return iter(self._classes.values())

    def palette(self) -> list[dict]:
        """
        Описание узлов для палитры редактора: type_id, категория, порты, схема
        параметров. UI рисует кнопки/формы из этого, не зная конкретных классов.
        """
        out: list[dict] = []
        for cls in self._classes.values():
            # Порты считаем на «пустом» экземпляре, где это возможно;
            # динамические (var_dict/block_list) отдают статический шаблон.
            out.append({
                "type_id": cls.type_id,
                "category": cls.category,
                "display_name": cls.display_name or cls.type_id,
                "description": cls.description,
                "inputs": [(p.name, p.type.value) for p in cls.INPUTS],
                "outputs": [(p.name, p.type.value) for p in cls.OUTPUTS],
                "params_schema": cls.PARAMS_SCHEMA,
            })
        return out
