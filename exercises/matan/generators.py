"""
Адаптеры модулей математического анализа.

Оригинальные функции в diff/ и limits/ не меняются. Они возвращают
кортежи вида (("text"|"formula", content), ...) — этот формат
здесь конвертируется в список Block'ов.
"""

from __future__ import annotations
from typing import Callable, Sequence, Tuple

from core import (
    TaskGenerator, StaticTask, TextBlock, FormulaBlock, Block, STATIC_DEFAULT
)

# diff
from .diff.just_diff import get_just_diff
from .diff.ln_diff import get_ln_diff
from .diff.ln_secret_diff import get_ln_secret_diff
from .diff.neyawn_diff import get_neyawn_diff
from .diff.parametric_task import get_parametric_task
from .diff.kasat import get_tangent_line
from .diff.lopital_law import get_lopital_law
from .diff.teylor import get_taylor_limit_task

# limits
from .limits.breaking_points import get_breaking_points
from .limits.c_k_equals import get_c_k_equals
from .limits.drob_radicals import get_drob_radicals
from .limits.easy_equals import get_easy_equals
from .limits.equals import get_equals
from .limits.lim_opr import get_lim_opr
from .limits.long_radicals import get_long_radicals
from .limits.perfect_1_2 import get_1_2_perfect
from .limits.second_perfect import get_2_perfect
from .limits.simple_osn import get_simple_osn
from .limits.simple_stepens import get_simple_stepens
from .limits.simple_stepens_radicals import get_simple_stepens as get_simple_stepens_radicals
from .limits.super_easy_equals import get_super_easy_equals


# ---------- Преобразование старого формата ----------

ContentTuple = Tuple[str, str]


def _to_block(item: ContentTuple) -> Block:
    """
    Преобразовать ('text'|'formula', content) → нужный Block.

    Любое не-строковое значение приводится к строке через str(): некоторые
    функции матана (например, perfect_1_2.get_1_2_perfect) возвращают
    sympy-объекты вместо строк — защищаемся.
    """
    kind, content = item
    if not isinstance(content, str):
        content = str(content)
    if kind == "text":
        return TextBlock(content)
    if kind == "formula":
        return FormulaBlock(content)
    return TextBlock(content)


# ---------- Базовый адаптер ----------

class _LegacyMatanAdapter(TaskGenerator):
    """
    Универсальная обёртка над функцией-генератором матана.

    Атрибут `description` — текст-описание задания на русском.
    Адаптер сам кладёт его как TextBlock перед содержимым задания, что
    обеспечивает единообразие: и diff-функции (которые возвращают свой
    встроенный заголовок), и limits-функции (которые возвращают только
    формулу) представляются пользователю одинаково — «текст условия +
    отрендеренная формула».

    Если description пустой, адаптер положится на встроенный заголовок
    diff-функций (3-tuple с первым элементом-описанием).
    """

    capabilities = STATIC_DEFAULT
    _legacy_func: Callable
    description: str = ""

    def generate(self) -> StaticTask:
        result = self._legacy_func()
        return self._build_task(result)

    def _build_task(self, result: Sequence[ContentTuple]) -> StaticTask:
        statement: list[Block] = []
        # Описание из класса — единообразный заголовок
        if self.description:
            statement.append(TextBlock(self.description))

        if len(result) == 3:
            # 3-tuple: (desc, cond, ans) — типично для diff
            desc, cond, ans = result
            # Если у класса нет своего description, используем встроенный
            if not self.description:
                statement.append(_to_block(desc))
            statement.append(_to_block(cond))
            answer = [_to_block(ans)]
        elif len(result) == 2:
            # 2-tuple: (cond, ans) — типично для limits
            cond, ans = result
            statement.append(_to_block(cond))
            answer = [_to_block(ans)]
        else:
            raise ValueError(f"Неподдерживаемый размер кортежа: {len(result)}")

        return StaticTask(statement=statement, answer=answer)


# ---------- DIFF: partition_id 40–47 ----------

class JustDiffGenerator(_LegacyMatanAdapter):
    name = "Обычные производные"
    partition_id = 40
    _legacy_func = staticmethod(get_just_diff)


class LnDiffGenerator(_LegacyMatanAdapter):
    name = "Логарифмические производные"
    partition_id = 41
    _legacy_func = staticmethod(get_ln_diff)


class LnSecretDiffGenerator(_LegacyMatanAdapter):
    name = "Неявные логарифмические производные"
    partition_id = 42
    _legacy_func = staticmethod(get_ln_secret_diff)


class NeyawnDiffGenerator(_LegacyMatanAdapter):
    name = "Неявно заданная функция"
    partition_id = 43
    _legacy_func = staticmethod(get_neyawn_diff)


class ParametricGenerator(_LegacyMatanAdapter):
    name = "Параметрически заданная производная"
    partition_id = 44
    _legacy_func = staticmethod(get_parametric_task)


class TangentGenerator(_LegacyMatanAdapter):
    name = "Касательные к функции"
    partition_id = 45
    _legacy_func = staticmethod(get_tangent_line)


class LopitalGenerator(_LegacyMatanAdapter):
    name = "Задания на Лопиталя"
    partition_id = 46
    _legacy_func = staticmethod(get_lopital_law)


class TaylorGenerator(_LegacyMatanAdapter):
    name = "Разложение по формуле Тейлора"
    partition_id = 47
    _legacy_func = staticmethod(get_taylor_limit_task)


# ---------- LIMITS: partition_id 50–62 ----------
#
# В отличие от diff-функций (3-tuple с встроенным заголовком), limits
# возвращают 2-tuple без описания. Поэтому каждому limits-классу даём
# свой `description` — он будет показан как TextBlock перед формулой.

_LIMIT_TASK = "Вычислить предел функции."


class SuperEasyEqualsGenerator(_LegacyMatanAdapter):
    name = "Простейшие пределы"
    partition_id = 50
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_super_easy_equals)


class EasyEqualsGenerator(_LegacyMatanAdapter):
    name = "Простые пределы"
    partition_id = 51
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_easy_equals)


class EqualsGenerator(_LegacyMatanAdapter):
    name = "Пределы стандартные"
    partition_id = 52
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_equals)


class CKEqualsGenerator(_LegacyMatanAdapter):
    name = "Замечательные пределы (C, k)"
    partition_id = 53
    description = "Определить C и k, при которых функции эквивалентны при x → 0."
    _legacy_func = staticmethod(get_c_k_equals)


class Perfect12Generator(_LegacyMatanAdapter):
    name = "Первый замечательный предел"
    partition_id = 54
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_1_2_perfect)


class SecondPerfectGenerator(_LegacyMatanAdapter):
    name = "Второй замечательный предел"
    partition_id = 55
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_2_perfect)


class SimpleStepensGenerator(_LegacyMatanAdapter):
    name = "Пределы со степенями"
    partition_id = 56
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_simple_stepens)


class SimpleStepensRadicalsGenerator(_LegacyMatanAdapter):
    name = "Пределы со степенями и радикалами"
    partition_id = 57
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_simple_stepens_radicals)


class DrobRadicalsGenerator(_LegacyMatanAdapter):
    name = "Дробно-радикальные пределы"
    partition_id = 58
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_drob_radicals)


class LongRadicalsGenerator(_LegacyMatanAdapter):
    name = "Длинные радикалы"
    partition_id = 59
    description = _LIMIT_TASK
    _legacy_func = staticmethod(get_long_radicals)


class SimpleOsnGenerator(_LegacyMatanAdapter):
    name = "Пределы по основному правилу"
    partition_id = 60
    description = "Вычислить предел последовательности."
    _legacy_func = staticmethod(lambda: get_simple_osn("easy"))


class LimOprGenerator(_LegacyMatanAdapter):
    name = "Пределы числовых последовательностей"
    partition_id = 61
    description = "ε-δ определение предела функции, геометрическая интерпретация."
    _legacy_func = staticmethod(get_lim_opr)


class BreakingPointsGenerator(_LegacyMatanAdapter):
    name = "Точки разрыва"
    partition_id = 62
    description = "Найти точки разрыва функции y = f(x) и определить их тип."
    _legacy_func = staticmethod(get_breaking_points)


# ---------- Регистрация ----------

def diff_generators() -> list[TaskGenerator]:
    return [
        JustDiffGenerator(),
        LnDiffGenerator(),
        LnSecretDiffGenerator(),
        NeyawnDiffGenerator(),
        ParametricGenerator(),
        TangentGenerator(),
        LopitalGenerator(),
        TaylorGenerator(),
    ]


def limits_generators() -> list[TaskGenerator]:
    return [
        SuperEasyEqualsGenerator(),
        EasyEqualsGenerator(),
        EqualsGenerator(),
        CKEqualsGenerator(),
        Perfect12Generator(),
        SecondPerfectGenerator(),
        SimpleStepensGenerator(),
        SimpleStepensRadicalsGenerator(),
        DrobRadicalsGenerator(),
        LongRadicalsGenerator(),
        SimpleOsnGenerator(),
        LimOprGenerator(),
        BreakingPointsGenerator(),
    ]


def all_generators() -> list[TaskGenerator]:
    return diff_generators() + limits_generators()
