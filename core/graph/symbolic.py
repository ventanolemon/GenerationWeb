"""
Символьная арифметика поверх sympy — общие помощники.

Здесь сосредоточены: ленивый импорт sympy (движок графа в остальном headless и
не должен падать на этапе загрузки, если sympy не установлен), безопасный разбор
пользовательских выражений и единая обёртка ошибок.

Узлы символьной арифметики (core/graph/nodes/symbolic.py) переносят между собой
объекты sympy через PortType.EXPR — это чистый round-trip без потерь (в отличие
от сериализации в LaTeX и обратно). Рендер в задание — через FormulaBlock(latex).
"""

from __future__ import annotations

import re

from .errors import GraphValidationError, RetryGeneration


# Имена sympy-функций, разрешённые в пользовательском вводе выражений. Этого
# набора достаточно для алгебры, мат. анализа, рядов и ТФКП.
_ALLOWED_FUNCS = (
    "sin cos tan cot sec csc asin acos atan acot sinh cosh tanh "
    "exp log ln sqrt Abs sign factorial gamma "
    "re im arg conjugate Heaviside DiracDelta"
).split()


def sympy():
    """Ленивый импорт sympy с понятной ошибкой, если он не установлен."""
    try:
        import sympy  # noqa: F401
    except Exception as e:  # pragma: no cover - окружение без sympy
        raise GraphValidationError(
            "Для символьной арифметики нужен пакет sympy (pip install sympy). "
            f"Импорт не удался: {e}"
        )
    return sympy


def build_symbols(names, assumptions: str = "complex") -> dict:
    """
    Создать словарь sympy-символов с заданными предположениями.

    assumptions: 'complex' (по умолчанию — без ограничений), 'real', 'positive'.
    Предположения важны для ТФКП и упрощений (например, re(x)=x при real).
    """
    sp = sympy()
    kw = {}
    if assumptions == "real":
        kw = {"real": True}
    elif assumptions == "positive":
        kw = {"positive": True}
    return {n: sp.Symbol(n, **kw) for n in names}


def parse_expr(text: str, symbols: dict | None = None):
    """
    Безопасно разобрать строку в sympy-выражение.

    Используется sympify с локальным словарём символов (с предположениями) и
    запретом на eval-конструкции. Степень принимает и '^', и '**'.
    """
    sp = sympy()
    if text is None or str(text).strip() == "":
        raise GraphValidationError("Пустое символьное выражение.")
    src = str(text).replace("^", "**")
    local = dict(symbols or {})
    # Мнимая единица: разрешаем и 'I' (sympy), и 'i' — если пользователь не
    # объявил 'i' как обычный символ.
    local.setdefault("I", sp.I)
    if "i" not in local:
        local["i"] = sp.I
    try:
        from sympy.parsing.sympy_parser import (
            parse_expr as _pe, standard_transformations,
            implicit_multiplication_application,
        )
        transforms = standard_transformations + (
            implicit_multiplication_application,
        )
        return _pe(src, local_dict=local, transformations=transforms,
                   evaluate=True)
    except GraphValidationError:
        raise
    except Exception as e:
        raise GraphValidationError(f"Не удалось разобрать выражение {text!r}: {e}")


def to_latex(expr) -> str:
    """LaTeX-представление sympy-выражения (через core.latex.canonical_latex)."""
    sp = sympy()
    raw = sp.latex(expr)
    try:
        from core.latex import canonical_latex
        return canonical_latex(raw)
    except Exception:
        return raw


def as_expr(value, symbols: dict | None = None):
    """
    Привести произвольное входное значение к sympy-выражению.

    EXPR-порт несёт sympy-объект как есть; число превращаем в sympy-число;
    строку разбираем parse_expr. Удобно для узлов, принимающих смешанные входы.
    """
    sp = sympy()
    if isinstance(value, sp.Basic):
        return value
    if isinstance(value, (int, float)):
        return sp.nsimplify(value) if isinstance(value, int) else sp.Float(value)
    return parse_expr(str(value), symbols)


def guard_numeric(expr):
    """
    Если выражение после операции стало нечисловым из-за деления на ноль и т.п.
    (sympy.zoo/oo/nan) — попросить пере-генерацию (как делает FormulaNode).
    """
    sp = sympy()
    if expr in (sp.zoo, sp.oo, -sp.oo, sp.nan):
        raise RetryGeneration(f"Символьный результат не определён: {expr}.")
    return expr


# ---------- Матрицы ----------

def parse_matrix(text: str, symbols: dict | None = None):
    """
    Разобрать строку в sympy.Matrix. Строки матрицы разделяются ';', элементы
    в строке — ','. Например '1,2;3,4' → [[1,2],[3,4]]; вектор-столбец '1;2;3'.
    Элементы разбираются parse_expr (допускают символы и дроби).
    """
    sp = sympy()
    if text is None or str(text).strip() == "":
        raise GraphValidationError("Пустая матрица.")
    rows = []
    for rline in str(text).split(";"):
        rline = rline.strip()
        if rline == "":
            continue
        cells = [parse_expr(c, symbols) for c in rline.split(",")]
        rows.append(cells)
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise GraphValidationError(
            f"Матрица {text!r}: строки разной длины."
        )
    return sp.Matrix(rows)


def is_matrix(value) -> bool:
    sp = sympy()
    return isinstance(value, sp.matrices.MatrixBase)


def as_matrix(value, symbols: dict | None = None):
    """Привести вход к sympy.Matrix (объект MATRIX-порта как есть; строку парсим)."""
    if is_matrix(value):
        return value
    return parse_matrix(str(value), symbols)


def substitute_values(obj, values: dict | None):
    """
    Подставить именованные числа в sympy-объект (выражение/матрицу/уравнение).

    values — dict[str, число] (как из NUMBER_DICT-порта). Символы-плейсхолдеры
    с этими именами заменяются значениями; прочие свободные символы остаются
    (так задаётся «форма со случайными коэффициентами»). None/пусто — без изменений.
    """
    if not values:
        return obj
    sp = sympy()
    mapping = {sp.Symbol(str(k)): _num(sp, v) for k, v in values.items()}
    try:
        return obj.subs(mapping)
    except AttributeError:
        return obj


def _num(sp, v):
    """Число (int/float) → точный sympy-объект (целые остаются целыми)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return sp.sympify(v)
    if abs(f - round(f)) < 1e-9:
        return sp.Integer(int(round(f)))
    return sp.Float(f)


# ---------- ОДУ ----------

def parse_ode(text: str, func: str = "y", var: str = "x"):
    """
    Разобрать ОДУ в sympy.Eq, поддерживая «человеческую» нотацию штрихов:
    y' → y'(x), y'' → вторая производная и т.д.; одиночное y → y(x).
    '=' разделяет левую и правую части (без '=' выражение трактуется как «… = 0»).
    Возвращает кортеж (eq, f, v): уравнение, sympy.Function f, переменная v.
    """
    sp = sympy()
    if text is None or str(text).strip() == "":
        raise GraphValidationError("Пустое уравнение ОДУ.")
    f = sp.Function(func)
    v = sp.Symbol(var)
    s = str(text)
    # Штрихи (от старших к младшим, чтобы '' не съелось до ').
    s = s.replace(func + "'''", f"Derivative({func}({var}),{var},3)")
    s = s.replace(func + "''", f"Derivative({func}({var}),{var},2)")
    s = s.replace(func + "'", f"Derivative({func}({var}),{var},1)")
    # Одиночное имя функции без скобки/буквы рядом → f(var).
    s = re.sub(rf"\b{func}\b(?!\s*[\(\w])", f"{func}({var})", s)
    s = s.replace("^", "**")
    local = {func: f, var: v, "Derivative": sp.Derivative, "e": sp.E}
    from sympy.parsing.sympy_parser import (
        parse_expr as _pe, standard_transformations,
        implicit_multiplication_application,
    )
    transforms = standard_transformations + (
        implicit_multiplication_application,
    )

    def one(part):
        return _pe(part, local_dict=local, transformations=transforms,
                   evaluate=True)

    try:
        if "=" in s:
            lhs, rhs = s.split("=", 1)
            eq = sp.Eq(one(lhs), one(rhs))
        else:
            eq = sp.Eq(one(s), 0)
    except Exception as e:
        raise GraphValidationError(f"Не удалось разобрать ОДУ {text!r}: {e}")
    return eq, f, v

