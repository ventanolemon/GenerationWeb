"""
Парсинг и вычисление формул физических задач.

Поддерживаемый «удобный» синтаксис в формулах и диапазонах:
  * Степени:        2^x       → 2**x
  * Корень:         sqrt(x), √(x), √x
  * Константы:      π, pi, e
  * Стандартные функции: sin, cos, tan, log, log10, log2, exp, abs

Унарный минус, скобки, операторы +, -, *, /, %, // работают как обычно.

Всё, что не входит в этот список — отвергается ещё на этапе парсинга,
никакого eval с произвольным кодом нет.
"""

from __future__ import annotations
import ast
import math
import re
from typing import Any, Mapping


# ---------- Допустимые функции и константы ----------

ALLOWED_FUNCTIONS = {
    "sin":   math.sin,
    "cos":   math.cos,
    "tan":   math.tan,
    "asin":  math.asin,
    "acos":  math.acos,
    "atan":  math.atan,
    "sqrt":  math.sqrt,
    "log":   math.log,           # натуральный, по основанию e
    "ln":    math.log,           # синоним
    "log10": math.log10,
    "log2":  math.log2,
    "exp":   math.exp,
    "abs":   abs,
    "floor": math.floor,
    "ceil":  math.ceil,
    "round": round,
}

# Математические константы. Имеют приоритет ниже пользовательских переменных:
# если пользователь объявил переменную с таким же именем, она перекрывает.
DEFAULT_CONSTANTS = {
    "pi":  math.pi,
    "π":   math.pi,
    "e":   math.e,                # Внимание: имя 'e' конфликтует с числами вида '1e3'.
                                  # Но в AST это разные сущности, проблемы нет.
    # Часто используемые физические константы. Пользователь их может перекрыть
    # своей переменной с тем же именем — она имеет приоритет в evaluate_formula.
    "g":   9.81,                  # ускорение свободного падения, м/с²
    "G":   6.6743e-11,            # гравитационная постоянная, Н·м²/кг²
    "c":   2.998e8,               # скорость света в вакууме, м/с
    "h":   6.626e-34,             # постоянная Планка, Дж·с
    "k_B": 1.381e-23,             # постоянная Больцмана, Дж/К
    "N_A": 6.022e23,              # число Авогадро, моль⁻¹
    "R_g": 8.314,                 # универсальная газовая постоянная, Дж/(моль·К)
}


# ---------- Нормализация удобной нотации ----------

# Преобразуем «человеческий» синтаксис в Python:
#   2^x          → 2**x
#   √(x+1)       → sqrt((x+1))
#   √x           → sqrt(x)              — только для одной буквы/числа
#
# Регулярки применяются к исходной строке. Это достаточно надёжно для нашей
# предметной области (формулы — короткие выражения).

_RE_CARET_POWER = re.compile(r"\^")
_RE_SQRT_SYM = re.compile(r"√")


def _normalize_expression(text: str) -> str:
    """Преобразовать удобный синтаксис формулы в стандартный Python."""
    s = text.strip()
    # ^ → **
    s = _RE_CARET_POWER.sub("**", s)
    # √(...)/√x → sqrt(...)
    # Идём последовательно: сначала √( → sqrt(
    s = s.replace("√(", "sqrt(")
    # Затем оставшиеся одиночные √x → sqrt(x); только перед именем/числом
    s = re.sub(r"√([A-Za-z_]\w*|\d+(?:\.\d+)?)", r"sqrt(\1)", s)
    # На всякий случай убираем оставшиеся √
    s = _RE_SQRT_SYM.sub("sqrt", s)
    # π напрямую (если осталось как имя)
    # Ничего больше не делаем — π уже в DEFAULT_CONSTANTS.
    return s


# ---------- Безопасный AST-калькулятор ----------

class FormulaError(ValueError):
    """Ошибка разбора или вычисления формулы."""


# Узлы AST, которые мы разрешаем
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp, ast.UnaryOp,
    ast.Num, ast.Constant,
    ast.Name, ast.Load,
    ast.Call,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.USub, ast.UAdd,
)


def _validate_ast(tree: ast.AST) -> None:
    """Проверить, что в дереве только допустимые узлы и вызовы."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(
                f"Недопустимая конструкция в формуле: {type(node).__name__}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError("Разрешены только прямые вызовы функций.")
            if node.func.id not in ALLOWED_FUNCTIONS:
                raise FormulaError(
                    f"Функция {node.func.id!r} не разрешена. "
                    f"Доступны: {sorted(ALLOWED_FUNCTIONS)}"
                )


def parse_formula(text: str) -> ast.Expression:
    """
    Разобрать формулу и вернуть проверенное AST-дерево.
    Бросает FormulaError при ошибках синтаксиса или недопустимых конструкциях.
    """
    normalized = _normalize_expression(text)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Синтаксическая ошибка в формуле: {e.msg}") from e
    _validate_ast(tree)
    return tree


def evaluate_formula(
    formula: str | ast.Expression,
    variables: Mapping[str, Any],
) -> float:
    """
    Вычислить формулу в контексте переменных.

    formula: строка (будет разобрана) или уже разобранное AST.
    variables: словарь имя→значение.

    Бросает FormulaError при недопустимых конструкциях или неизвестных именах.
    Числовые ошибки (OverflowError, ZeroDivisionError, ValueError для domain
    errors) пробрасываются наверх — вызывающий сам решает, что с ними делать.
    """
    tree = formula if isinstance(formula, ast.Expression) else parse_formula(formula)

    # Собираем рабочий namespace: константы + пользовательские переменные.
    # Пользовательские переменные перекрывают константы.
    scope = {**DEFAULT_CONSTANTS, **variables}

    return _eval_node(tree.body, scope)


def _eval_node(node: ast.AST, scope: Mapping[str, Any]) -> Any:
    """Рекурсивный вычислитель для проверенного AST."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise FormulaError(f"Недопустимая константа: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise FormulaError(f"Неизвестная переменная: {node.id!r}")

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, scope)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise FormulaError(f"Недопустимый унарный оператор: {type(node.op).__name__}")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, scope)
        right = _eval_node(node.right, scope)
        op = node.op
        if isinstance(op, ast.Add):      return left + right
        if isinstance(op, ast.Sub):      return left - right
        if isinstance(op, ast.Mult):     return left * right
        if isinstance(op, ast.Div):      return left / right
        if isinstance(op, ast.FloorDiv): return left // right
        if isinstance(op, ast.Mod):      return left % right
        if isinstance(op, ast.Pow):      return left ** right
        raise FormulaError(f"Недопустимый бинарный оператор: {type(op).__name__}")

    if isinstance(node, ast.Call):
        func_name = node.func.id          # уже проверено в _validate_ast
        func = ALLOWED_FUNCTIONS[func_name]
        args = [_eval_node(a, scope) for a in node.args]
        return func(*args)

    raise FormulaError(f"Неподдерживаемый узел AST: {type(node).__name__}")


def extract_variable_names(text: str) -> set[str]:
    """
    Вернуть множество имён переменных, использованных в формуле,
    исключая имена встроенных функций и стандартных констант.
    """
    tree = parse_formula(text)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in ALLOWED_FUNCTIONS \
                and node.id not in DEFAULT_CONSTANTS:
            names.add(node.id)
    return names
