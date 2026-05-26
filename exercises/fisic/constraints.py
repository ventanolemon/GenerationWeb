"""
Ограничения на результат генерируемой задачи.

Конфигурация в JSON под ключом 'result':

  "result": {
    "kind": "natural",        // natural | integer | real
    "min": 1,                 // опционально
    "max": 1000,              // опционально
    "tolerance": 1e-9         // опционально, для проверки целочисленности
  }

Если задача — «найти количество страниц», ставим kind=natural — генератор
будет повторять попытки, пока результат формулы не получится натуральным.

Если result не указан, никаких проверок не накладывается (поведение совпадает
со старым).

min/max могут быть формулами, как в VariableSpec.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field

from .generation import _evaluate_or_float


@dataclass
class ResultConstraint:
    """Ограничения на результат вычисления формулы."""
    kind: str = "real"               # 'natural' | 'integer' | 'real'
    min_val: float | None = None
    max_val: float | None = None
    tolerance: float = 1e-9          # допуск при проверке целочисленности

    def __post_init__(self):
        if self.kind not in ("natural", "integer", "real"):
            raise ValueError(
                f"ResultConstraint: kind={self.kind!r} не поддерживается."
            )

    @classmethod
    def parse(cls, config: dict | None) -> "ResultConstraint":
        if not config:
            return cls()  # без ограничений (kind='real', нет min/max)
        kind = config.get("kind", "real")
        raw_min = config.get("min")
        raw_max = config.get("max")
        min_val = _evaluate_or_float(raw_min) if raw_min not in (None, "") else None
        max_val = _evaluate_or_float(raw_max) if raw_max not in (None, "") else None
        tol = float(config.get("tolerance", 1e-9))
        return cls(kind=kind, min_val=min_val, max_val=max_val, tolerance=tol)

    def check(self, value: float) -> bool:
        """Удовлетворяет ли значение ограничениям."""
        # Базовые проверки на корректность числа
        if math.isinf(value) or math.isnan(value):
            return False

        # Целочисленность
        if self.kind in ("natural", "integer"):
            if abs(value - round(value)) > self.tolerance:
                return False

        # Натуральность = целое + положительное
        if self.kind == "natural":
            if round(value) < 1:
                return False

        # Границы
        if self.min_val is not None and value < self.min_val - self.tolerance:
            return False
        if self.max_val is not None and value > self.max_val + self.tolerance:
            return False

        return True

    def normalize(self, value: float) -> float:
        """
        Привести значение к каноническому виду:
          natural/integer → ровное целое
          real            → как есть
        Считаем, что check() уже прошёл успешно.
        """
        if self.kind in ("natural", "integer"):
            return float(round(value))
        return value
