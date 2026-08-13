"""
Когда два уравнения задают одно и то же.

Третий случай того же устройства, что `boolean_text` и `program_output`:
определение равенства нужно и модели (`Instance.equivalent`), и проверке
ответа (`EquationSpec`), поэтому лежит в одном месте.

Правило. Уравнение вида `F(x, y, …) = 0` описывает множество, а не
выражение: `3x + 2y - 5 = 0`, `6x + 4y - 10 = 0` и `-3x - 2y + 5 = 0` —
одна и та же прямая. Поэтому равенство здесь — **пропорциональность**, а
не алгебраическое тождество. Обычная проверка выражений
(`simplify(a - b) == 0`) забраковала бы два верных ответа из трёх, и
студент не понял бы, за что.

Годится не только прямой: плоскость, поверхность второго порядка — всё,
что записывается как «выражение = 0».
"""

from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"[A-Za-zА-Яа-я_][A-Za-zА-Яа-я_0-9]*")


class EquationTextError(ValueError):
    """Запись не удалось прочитать. Сообщение адресовано человеку."""


def as_expression(value, variables):
    """
    Текст уравнения → выражение sympy, равное нулю на его множестве.

    Принимается и `3x + 2y - 5 = 0`, и `3x + 2y = 5`, и просто левая
    часть. Знак равенства переносится вычитанием: студент пишет уравнение,
    а сравнивать удобнее выражения.

    Безопасность — белым списком ИМЁН, а не доверием к разборщику:
    `parse_expr` исполняет разобранное, поэтому любое имя вне списка
    переменных отвергается ДО разбора. Тот же приём, что у
    `ExpressionSpec._parse`; здесь он повторён, а не переиспользован,
    чтобы `core.answers` мог зависеть от этого модуля, а не наоборот.
    """
    import sympy as sp

    if isinstance(value, sp.Basic):
        return value

    text = str(value).strip()
    if not text:
        raise EquationTextError("пустая запись")
    if text.count("=") > 1:
        raise EquationTextError("в уравнении больше одного знака равенства")
    if "=" in text:
        left, right = text.split("=")
        if not left.strip() or not right.strip():
            raise EquationTextError("у знака равенства пустая сторона")
        text = f"({left}) - ({right})"

    source = text.replace("^", "**")
    allowed = {str(v) for v in variables}
    for name in _IDENTIFIER.findall(source):
        if name not in allowed:
            raise EquationTextError(
                f"неизвестное имя {name!r}; в задании есть "
                f"{', '.join(sorted(allowed))}")

    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application, standard_transformations,
    )

    try:
        return sp.parsing.sympy_parser.parse_expr(
            source,
            transformations=(standard_transformations
                             + (implicit_multiplication_application,)),
            local_dict={name: sp.Symbol(name) for name in allowed},
            evaluate=True)
    except Exception as exc:                              # noqa: BLE001
        raise EquationTextError("уравнение не разобрано") from exc


def proportional(left, right, variables) -> bool:
    """
    Задают ли `left = 0` и `right = 0` одно множество.

    Проверяется через коэффициенты: два многочлена пропорциональны тогда и
    только тогда, когда отношение их коэффициентов при одинаковых
    одночленах постоянно. Сравнивать «на глаз» через `simplify(l/r)`
    нельзя — у нулевых коэффициентов отношение не определено, и результат
    зависел бы от того, какой одночлен попался первым.

    Нулевое выражение уравнением не является: `0 = 0` выполняется везде и
    прямой не задаёт.
    """
    import sympy as sp

    symbols = [sp.Symbol(str(v)) for v in variables]
    try:
        first = sp.Poly(sp.expand(left), *symbols)
        second = sp.Poly(sp.expand(right), *symbols)
    except sp.PolynomialError:
        return False
    if first.is_zero or second.is_zero:
        return False

    terms = dict(first.terms())
    others = dict(second.terms())
    if set(terms) != set(others):
        return False

    ratio = None
    for monomial, coefficient in terms.items():
        other = others[monomial]
        current = sp.simplify(other / coefficient)
        if ratio is None:
            ratio = current
        elif sp.simplify(current - ratio) != 0:
            return False
    return ratio is not None and ratio != 0


def same_equation(expected, answer, variables) -> bool:
    """Одно ли уравнение — с разбором текста и всеми оговорками выше."""
    try:
        left = as_expression(expected, variables)
        right = as_expression(answer, variables)
    except EquationTextError:
        return False
    return proportional(left, right, variables)


def format_equation(expr, variables) -> str:
    """
    Выражение → привычная запись `A*x + B*y + C = 0`.

    Ключ читает человек, и `3*x + 2*y - 5` без «= 0» — это выражение, а в
    задании спрашивали уравнение.
    """
    import sympy as sp

    return f"{sp.expand(expr)} = 0"


def normalise(expr, variables):
    """
    Уравнение с целыми взаимно простыми коэффициентами и старшим > 0.

    Каноническая запись нужна не проверке (она и так по
    пропорциональности), а ПОКАЗУ: ключ с `-6x - 4y + 10 = 0` там, где
    достаточно `3x + 2y - 5 = 0`, выглядит небрежностью и заставляет
    сверять руками.
    """
    import sympy as sp

    symbols = [sp.Symbol(str(v)) for v in variables]
    poly = sp.Poly(sp.expand(expr), *symbols)
    coefficients = poly.coeffs()
    if not coefficients:
        return sp.Integer(0)
    common = sp.gcd([sp.nsimplify(c) for c in coefficients])
    if common == 0:
        return sp.expand(expr)
    result = sp.expand(sp.together(expr / common))
    lead = sp.Poly(result, *symbols).coeffs()[0]
    return sp.expand(-result) if lead < 0 else result
