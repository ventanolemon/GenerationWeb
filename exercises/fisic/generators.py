"""
Адаптер физического конструктора задач.

Один FisicConstructorGenerator обслуживает все физические разделы.
Каждый раздел в БД хранит свой JSON в generation_parametrs; адаптер
передаёт его в generate_task.

Нормализация типов (строки → числа, формулы в диапазонах, и т.п.)
делается уровнем ниже — в TaskConfig.parse / parse_variable_spec.
Адаптер просто передаёт конфиг как есть.
"""

from __future__ import annotations
import json

from core import (
    TaskGenerator, StaticTask, TextBlock, STATIC_DEFAULT
)
from .fisic_generater import generate_fisic_task


class FisicConstructorGenerator(TaskGenerator):
    """Универсальный генератор для физических задач из БД."""

    name = "Физическая задача"
    capabilities = STATIC_DEFAULT

    def __init__(self, partition_id: int, name: str, config: str | dict):
        self.partition_id = partition_id
        self.name = name
        self._config = self._to_dict(config)

    def configure(self, params: dict) -> None:
        """Обновить конфиг из БД (зовётся реестром при выдаче)."""
        if not params:
            return
        if "raw" in params:
            self._config = self._to_dict(params["raw"])
        else:
            # Repository вернул уже разобранный dict
            self._config = params

    def generate(self) -> StaticTask:
        condition, solution = generate_fisic_task(self._config)
        return StaticTask(
            statement=[TextBlock(condition)],
            answer=[TextBlock(solution)],
            meta={"partition_id": self.partition_id},
        )

    @staticmethod
    def _to_dict(config: str | dict) -> dict:
        """Привести входной конфиг к dict. Поддерживает str и dict."""
        if isinstance(config, dict):
            return config
        if isinstance(config, str):
            try:
                data = json.loads(config)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        return {}
