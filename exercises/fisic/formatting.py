"""
Форматирование чисел для вывода в условиях и решениях.

Унифицирует две раздельные функции из старого generator: format_result и
format_variable_value. Принимает явные параметры вместо встроенных порогов.

Особенности:
  * Целые числа выводятся без точки: 5 вместо 5.0
  * Научная нотация автоматически для очень больших/малых чисел
  * Ноль всегда — '0', не '0.000'
  * Убираются хвостовые нули в дробях ('1.5', не '1.50')
"""

from __future__ import annotations
import math


def format_number(
    value: float,
    *,
    decimals: int = 3,
    scientific_threshold_high: float = 1e4,
    scientific_threshold_low: float = 1e-3,
    scientific_significant: int = 3,
    integer_tolerance: float = 1e-10,
) -> str:
    """
    Универсальное форматирование числа.

    decimals — максимум знаков после запятой для обычных чисел.
    scientific_threshold_high — выше этого значения по модулю → научная нотация.
    scientific_threshold_low — ниже этого значения (но > 0) → научная нотация.
    scientific_significant — значащих цифр в научной нотации.
    integer_tolerance — допуск, при котором число считается целым.
    """
    if math.isinf(value):
        return "∞" if value > 0 else "-∞"
    if math.isnan(value):
        return "неопределено"

    abs_value = abs(value)
    # Чистый ноль
    if abs_value == 0:
        return "0"

    # Если число попадает в «крайности» (очень маленькое или очень большое) —
    # сразу в научную нотацию, не пытаясь округлить до целого.
    if abs_value < scientific_threshold_low or abs_value >= scientific_threshold_high:
        return _scientific(value, scientific_significant)

    # Целое? Проверка только в «нормальном» диапазоне.
    if abs(value - round(value)) < integer_tolerance:
        return str(int(round(value)))

    # Обычная запись: округляем до decimals и убираем хвостовые нули
    formatted = f"{value:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def _scientific(value: float, significant: int) -> str:
    """Научная нотация с указанным числом значащих цифр."""
    abs_value = abs(value)
    if abs_value == 0:
        return "0"
    exponent = math.floor(math.log10(abs_value))
    coefficient = value / (10 ** exponent)

    # Если коэффициент — почти целое число, пишем без дробной части
    if abs(coefficient - round(coefficient)) < 1e-10:
        coeff_str = str(int(round(coefficient)))
    else:
        coeff_str = f"{coefficient:.{max(0, significant - 1)}f}"
        # Убираем хвостовые нули
        if "." in coeff_str:
            coeff_str = coeff_str.rstrip("0").rstrip(".")

    return f"{coeff_str}×10^{exponent}"
