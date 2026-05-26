"""
Спецификация переменной и генерация значений с явными ограничениями.

Конфигурация переменной в JSON может выглядеть так:

  {
    "min": 1,
    "max": 100,
    "kind": "natural",        // natural | integer | real
    "step": 1,                // опционально: шаг сетки (например, 0.5 → только .0 и .5)
    "forbidden": [0],         // запрещённые значения
    "decimals": 2,            // округление для real (по умолчанию 2)
    "dimension": "кг"
  }

Бэк-совместимость: если 'kind' не указан, поведение совпадает со старым
(автоматический выбор «целое если диапазон ≥ 1, иначе округление до 2 знаков»).

Сами min/max могут быть формулами: "10^3", "2*pi", "sqrt(2)" — они будут
вычислены через expression.evaluate_formula().
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Any

from .expression import evaluate_formula


VarKind = str   # 'natural' | 'integer' | 'real' | 'auto'


@dataclass
class VariableSpec:
    """Описание одной переменной в задаче."""
    name: str
    min_val: float
    max_val: float
    kind: VarKind = "auto"          # auto = старое поведение
    step: float | None = None       # шаг сетки; для natural/integer по умолчанию 1
    forbidden: list[float] = field(default_factory=list)
    decimals: int = 2               # округление real-чисел
    dimension: str = ""

    def __post_init__(self):
        if self.max_val < self.min_val:
            raise ValueError(
                f"Переменная {self.name!r}: max ({self.max_val}) меньше "
                f"min ({self.min_val})."
            )
        if self.kind not in ("auto", "natural", "integer", "real"):
            raise ValueError(
                f"Переменная {self.name!r}: неизвестный kind={self.kind!r}. "
                f"Допустимы: auto, natural, integer, real."
            )
        if self.kind == "natural" and self.min_val < 1:
            # Принудительно поднимаем минимум до 1: натуральные ≥ 1
            self.min_val = max(self.min_val, 1)
            if self.max_val < 1:
                raise ValueError(
                    f"Переменная {self.name!r}: kind=natural требует max ≥ 1."
                )
        # Шаг по умолчанию для дискретных
        if self.step is None and self.kind in ("natural", "integer"):
            self.step = 1


# ---------- Загрузка спецификации из конфига БД ----------

def parse_variable_spec(name: str, config: dict) -> VariableSpec:
    """
    Превратить запись из generation_parametrs в VariableSpec.

    Поддерживает формулы в min/max ("10^3", "pi*2") и нормализует строки
    в числах (legacy: "0" вместо 0).
    """
    raw_min = config.get("min", 0)
    raw_max = config.get("max", 0)
    min_val = _evaluate_or_float(raw_min)
    max_val = _evaluate_or_float(raw_max)

    forbidden_raw = config.get("forbidden", [])
    if not isinstance(forbidden_raw, list):
        forbidden_raw = [forbidden_raw]
    forbidden: list[float] = []
    for item in forbidden_raw:
        try:
            forbidden.append(_evaluate_or_float(item))
        except (TypeError, ValueError):
            continue

    raw_step = config.get("step")
    step = _evaluate_or_float(raw_step) if raw_step not in (None, "") else None

    decimals_raw = config.get("decimals", 2)
    try:
        decimals = int(decimals_raw)
    except (TypeError, ValueError):
        decimals = 2

    return VariableSpec(
        name=name,
        min_val=min_val,
        max_val=max_val,
        kind=config.get("kind", "auto"),
        step=step,
        forbidden=forbidden,
        decimals=decimals,
        dimension=config.get("dimension", ""),
    )


def _evaluate_or_float(value: Any) -> float:
    """
    Превратить значение в float. Поддерживает:
      * числа (int, float)
      * строки с числом ("3", "0.5", "1e-3")
      * строки с формулой ("10^3", "pi*2", "sqrt(2)")
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("Пустая строка вместо числа.")
        # Сначала пробуем как обычное число
        try:
            return float(s)
        except ValueError:
            pass
        # Иначе — формула
        return float(evaluate_formula(s, {}))
    raise TypeError(f"Не могу превратить в число: {value!r}")


# ---------- Генерация значения по спецификации ----------

def generate_value(spec: VariableSpec, max_attempts: int = 50) -> float:
    """
    Сгенерировать одно значение, удовлетворяющее спецификации.
    Бросает RuntimeError, если не удалось за max_attempts попыток.
    """
    for _ in range(max_attempts):
        candidate = _draw_one(spec)
        if candidate is None:
            continue
        if _is_forbidden(candidate, spec.forbidden):
            continue
        return candidate

    raise RuntimeError(
        f"Не удалось сгенерировать значение для {spec.name!r} "
        f"за {max_attempts} попыток. Проверьте диапазон и forbidden."
    )


def _draw_one(spec: VariableSpec) -> float | None:
    """Один черновой draw — без проверки forbidden."""
    if spec.kind == "natural":
        # Целое в [max(1, ceil(min)), floor(max)] с шагом step
        lo = max(1, math.ceil(spec.min_val))
        hi = math.floor(spec.max_val)
        return _draw_discrete(lo, hi, spec.step or 1)

    if spec.kind == "integer":
        lo = math.ceil(spec.min_val)
        hi = math.floor(spec.max_val)
        return _draw_discrete(lo, hi, spec.step or 1)

    if spec.kind == "real":
        if spec.step:
            return _draw_grid(spec.min_val, spec.max_val, spec.step, spec.decimals)
        return round(random.uniform(spec.min_val, spec.max_val), spec.decimals)

    # kind == "auto" — старое поведение, для совместимости
    if spec.max_val - spec.min_val >= 1.0:
        lo = math.ceil(spec.min_val)
        hi = math.floor(spec.max_val)
        if lo <= hi:
            return float(random.randint(lo, hi))
    return round(random.uniform(spec.min_val, spec.max_val), 2)


def _draw_discrete(lo: int, hi: int, step: float) -> float | None:
    """Целое в [lo, hi] с шагом step (обычно 1)."""
    if lo > hi:
        return None
    if step == 1:
        return float(random.randint(lo, hi))
    # Шаг ≠ 1: количество позиций
    n_steps = int((hi - lo) // step)
    if n_steps < 0:
        return None
    k = random.randint(0, n_steps)
    return float(lo + k * step)


def _draw_grid(min_val: float, max_val: float, step: float, decimals: int) -> float:
    """Real-число на сетке с шагом step."""
    if step <= 0:
        return round(random.uniform(min_val, max_val), decimals)
    n_steps = int((max_val - min_val) / step)
    if n_steps <= 0:
        return round(min_val, decimals)
    k = random.randint(0, n_steps)
    return round(min_val + k * step, decimals)


def _is_forbidden(value: float, forbidden: list[float]) -> bool:
    if not forbidden:
        return False
    return any(abs(value - f) < 1e-9 for f in forbidden)
