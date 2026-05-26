"""
GeneratorRegistry — реестр модулей. Без изменений.
"""

from __future__ import annotations
from typing import Callable, Dict

from .generator import TaskGenerator


GeneratorFactory = Callable[[dict], TaskGenerator]


class GeneratorRegistry:
    def __init__(self):
        self._instances: Dict[int, TaskGenerator] = {}
        self._factories: Dict[int, GeneratorFactory] = {}

    def register(self, generator: TaskGenerator) -> None:
        if generator.partition_id is None:
            raise ValueError(
                f"Генератор {generator.name!r} не имеет partition_id — "
                "его нельзя положить в реестр."
            )
        self._instances[generator.partition_id] = generator

    def register_factory(self, partition_id: int, factory: GeneratorFactory) -> None:
        self._factories[partition_id] = factory

    def get(self, partition_id: int, params: dict | None = None) -> TaskGenerator:
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
