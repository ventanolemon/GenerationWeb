"""
GeneratorRegistry — реестр модулей.

При старте приложения все доступные генераторы регистрируются здесь.
По partition_id из БД реестр выдаёт нужный генератор.

Также поддерживает фабрики — для случаев, когда генератор требует
параметров из БД (например, конструктор физики или группа).
"""

from __future__ import annotations
from typing import Callable, Dict

from .generator import TaskGenerator


# Фабрика — функция, принимающая параметры из БД и возвращающая готовый генератор
GeneratorFactory = Callable[[dict], TaskGenerator]


class GeneratorRegistry:
    """Хранилище генераторов с поиском по partition_id."""

    def __init__(self):
        # уже готовые экземпляры
        self._instances: Dict[int, TaskGenerator] = {}
        # фабрики — для генераторов, которым нужны параметры из БД
        self._factories: Dict[int, GeneratorFactory] = {}

    def register(self, generator: TaskGenerator) -> None:
        """Зарегистрировать готовый экземпляр генератора."""
        if generator.partition_id is None:
            raise ValueError(
                f"Генератор {generator.name!r} не имеет partition_id — "
                "его нельзя положить в реестр."
            )
        self._instances[generator.partition_id] = generator

    def register_factory(
        self, partition_id: int, factory: GeneratorFactory
    ) -> None:
        """
        Зарегистрировать фабрику. Используется, если генератору нужно
        прочитать параметры из БД при создании.
        """
        self._factories[partition_id] = factory

    def get(self, partition_id: int, params: dict | None = None) -> TaskGenerator:
        """
        Получить генератор для раздела.

        Сначала ищется готовый экземпляр, затем фабрика.
        """
        if partition_id in self._instances:
            gen = self._instances[partition_id]
            if params is not None:
                gen.configure(params)
            return gen

        if partition_id in self._factories:
            return self._factories[partition_id](params or {})

        raise KeyError(
            f"Нет генератора для partition_id={partition_id}. "
            "Проверьте регистрацию в bootstrap."
        )

    def has(self, partition_id: int) -> bool:
        return partition_id in self._instances or partition_id in self._factories

    def all_ids(self) -> list[int]:
        return list(set(self._instances) | set(self._factories))
