"""
Контракт узла графа.

Один узел = один класс, наследующий Node (по образцу того, как Block = один
класс, и его подхватывают все View). Узел декларирует:
  * type_id     — строковый идентификатор для сериализации и реестра;
  * category    — source | compute | content | assembly (для палитры редактора);
  * INPUTS/OUTPUTS — статические порты (или динамические — через переопределение
                  input_ports()/output_ports(), как у var_dict и block_list);
  * PARAMS_SCHEMA — описание полей формы параметров (используется редактором);
  * compute()   — чистая функция: по входам и контексту вернуть выходы.

Узлы не хранят состояние между попытками: параметры фиксируются в __init__,
входы приходят в compute(), случайность берётся из контекста/глобального RNG.
"""

from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .errors import GraphValidationError
from .port_types import PortType


@dataclass(frozen=True)
class Port:
    """Описание одного порта узла."""
    name: str
    type: PortType
    required: bool = True


@dataclass
class ExecContext:
    """
    Контекст одного запуска графа.

    rng     — генератор случайных чисел для узлов, написанных в рамках движка
              (например, будущий random_choice). Узлы-источники физики
              (random_natural/real) переиспользуют generation.generate_value,
              который опирается на глобальный random; для воспроизводимости
              исполнитель сидит глобальный random перед циклом попыток.
    attempt — номер текущей попытки (0-based) в whole-graph retry.
    """
    rng: random.Random
    attempt: int = 0
    extra: dict = field(default_factory=dict)


class Node(ABC):
    """Базовый класс узла. Подклассы реализуют compute()."""

    type_id: str = ""
    category: str = ""
    display_name: str = ""
    description: str = ""        # краткое назначение узла (для палитры/инспектора)
    INPUTS: list[Port] = []
    OUTPUTS: list[Port] = []
    PARAMS_SCHEMA: dict = {}

    def __init__(self, node_id: str, params: dict | None = None):
        self.node_id = node_id
        self.params: dict = dict(params or {})
        self.validate_params()

    # --- Подклассы переопределяют по необходимости ---

    def validate_params(self) -> None:
        """Проверить self.params. Бросить GraphValidationError при ошибке."""
        return None

    def validate_structure(self) -> None:
        """
        Строгие структурные проверки сверх формата параметров — например,
        согласованность объявлений узла с его вложенным телом (туннели вывода
        repeat/map/case). Вызывается исполнителем при сборке графа; в отличие
        от validate_params НЕ дёргается редактором при отрисовке портов,
        поэтому может требовать полностью собранного тела.
        """
        return None

    def input_ports(self) -> list[Port]:
        """Входные порты. Переопределяется, если зависят от параметров."""
        return list(self.INPUTS)

    def output_ports(self) -> list[Port]:
        """Выходные порты. Переопределяется, если зависят от параметров."""
        return list(self.OUTPUTS)

    @abstractmethod
    def compute(self, inputs: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
        """
        Вычислить выходы по входам.

        inputs — значения, пришедшие на входные порты (ключ = имя порта).
        Возвращает dict: имя выходного порта → значение.
        Может бросить RetryGeneration, чтобы запросить пере-генерацию графа.
        """

    # --- Утилита для подклассов ---

    def _require_param(self, key: str) -> Any:
        if key not in self.params:
            raise GraphValidationError(
                f"Узел {self.node_id!r} ({self.type_id}): "
                f"не задан обязательный параметр {key!r}."
            )
        return self.params[key]
