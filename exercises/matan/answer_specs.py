"""
Проверяемая форма ответа для матана — второй пилот обогащения (§1 плана).

Чем матан отличается от физики
------------------------------
У физики был один конструктор и числовой результат: обогащение свелось к
тому, чтобы перестать выбрасывать уже посчитанное. Здесь двадцать одна
функция в двух пакетах, и ответ у них — **уже отрендеренный LaTeX**:
`sp.latex(answer)` стоит в последней строке, а сам `answer` — объект
sympy — исчезает вместе с кадром стека.

Разобрать LaTeX обратно нечем: `sympy.parsing.latex` требует antlr4,
которого нет, а свой разборщик подмножества LaTeX — это ровно «половина
алгебры, которая молча ошибается», от которой план отказывается в §1.

Поэтому два канала, и оба самопроверяемые.

Канал 1: показанный ответ, если он и так разбирается
----------------------------------------------------
Часть функций отдаёт ответ обычной строкой: `exp(3)`, `-3/32`, `1000`.
Это готовое выражение, и спецификация строится прямо из него, без единой
правки в самих функциях.

Канал 2: явное значение от функции
-----------------------------------
Функция может вернуть дополнительный элемент `("answer", <значение>)` —
sympy-объект или строку. Цена — одна строка на функцию, и именно ради
измерения этой цены пилот и делался.

Общее правило: спецификация прикрепляется, ТОЛЬКО если принимает
показанный ответ
-----------------------------------------------------------------
Ни один из каналов не верит себе на слово. Собранная спецификация
прогоняется по тому самому тексту, который увидит человек, и не прошла —
не прикрепляется. Так «обогащение» не может создать задание, которое
отвергает собственный ответ; худшее, что случается, — задание остаётся
непроверяемым, как и было.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence, Tuple

from core.answers import AnswerSpec, ExpressionSpec, SlotsSpec

#: Метка дополнительного элемента с проверяемым значением.
ANSWER_MARK = "answer"

#: «C=2**(1/4), k=1/4» — ответ из нескольких именованных величин.
#: Требуем, чтобы КАЖДАЯ часть была вида «имя=значение»: прозаическое
#: «x = -4, устранимая» под это не подходит и слотами не станет, а
#: угадывать смысл прозы — как раз то, чего делать нельзя.
_NAMED_PART = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")


def split_checkable(result: Sequence) -> Tuple[tuple, Optional[Any]]:
    """
    Отделить проверяемое значение от кортежа старого формата.

    Метка, а не позиция: кортежи бывают из двух и трёх элементов, и
    «четвёртый» означал бы разное в разных пакетах. `("answer", …)`
    читается одинаково в обоих и не путается с блоками показа.
    """
    items = tuple(result)
    if (items and isinstance(items[-1], (tuple, list))
            and len(items[-1]) == 2 and items[-1][0] == ANSWER_MARK):
        return items[:-1], items[-1][1]
    return items, None


def build(explicit: Any, shown: str) -> Optional[AnswerSpec]:
    """
    Спецификация ответа или None, если проверять нечем.

    Кандидаты пробуются по очереди: сначала явное значение от функции,
    потом показанный текст. Каждый — через собственную проверку.
    """
    for candidate in (explicit, shown):
        if candidate is None:
            continue
        text = _as_text(candidate)
        if not text:
            continue
        spec = _expression(text) or _slots(text)
        if spec is not None:
            return spec
    return None


def _as_text(value: Any) -> str:
    """
    Текст выражения. sympy-объект печатается своим `str`, а не латехом:
    спецификация хранит выражение строкой и разбирает его сама, по своему
    белому списку имён.
    """
    return str(value).strip()


def _expression(text: str) -> Optional[ExpressionSpec]:
    spec = ExpressionSpec(value=text)
    # `symbols` не задаём: пустой список означает «вывести из самого
    # ответа», и для производной с x это работает так же, как для
    # константы без переменных.
    try:
        return spec if spec.check(text).accepted else None
    except Exception:                                  # noqa: BLE001
        return None


def _slots(text: str) -> Optional[SlotsSpec]:
    parts = [p for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        return None

    slots = []
    for part in parts:
        match = _NAMED_PART.match(part)
        if match is None:
            return None                # хоть одна часть без имени — не слоты
        inner = _expression(match.group(2))
        if inner is None:
            return None
        slots.append((match.group(1), inner))

    spec = SlotsSpec(slots=tuple(slots))
    try:
        # Проверяем ПО ПОЛЯМ, а не по склеенной строке: разделителем
        # набора слотов в ядре служат «;» и перевод строки, а матан пишет
        # «C=…, k=…» через запятую. Отвечать всё равно будут в раздельные
        # поля (виджет slot_fields), и правило «спецификация обязана
        # принять показанный ответ» здесь проверяется в той же форме, в
        # какой ответ придёт.
        values = {name: inner.value for name, inner in slots}
        return spec if spec.check_slots(values).accepted else None
    except Exception:                                  # noqa: BLE001
        return None


__all__ = ["ANSWER_MARK", "split_checkable", "build"]
