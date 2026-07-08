"""
Узлы символьной арифметики (категория symbolic).

Выражения переносятся между узлами через PortType.EXPR как объекты sympy —
без сериализации в LaTeX и обратно, поэтому преобразования точны и без потерь.
Рендер в задание — узлом expr_block (EXPR → BLOCK через FormulaBlock).

PR-1 (ядро + алгебра): источники (symbol, expr_const), алгебраические операции
(expand/factor/simplify/collect/apart/together/cancel/trigsimp), подстановка
и численная оценка, сборка выражений в формулу. Мат. анализ, ряды и ТФКП —
следующими PR (узлы строятся по тому же образцу).

sympy импортируется лениво (см. core.graph.symbolic): движок графа headless и
не должен падать на загрузке, если пакет отсутствует.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType
from ..symbolic import (
    as_expr, build_symbols, guard_numeric, parse_expr, substitute_values,
    sympy, to_latex,
)


def _resolve_var(node, inputs, expr):
    """
    Переменная для diff/limit/integrate/… — без обязательного отдельного symbol.

    Приоритет: (1) подключённый вход var; (2) параметр var по имени — берётся
    тот же символ из выражения (с его предположениями), либо создаётся; (3) если
    в выражении ровно одна переменная — она. Иначе понятная ошибка (нет
    переменной / несколько — укажите var). Молча «угадывать» при нескольких
    переменных не станем — это и приводило к незаметно неверным ответам. Авто-
    вывод точнее ручного symbol: совпадение предположений гарантировано.
    """
    if inputs.get("var") is not None:
        return as_expr(inputs["var"])
    sp = sympy()
    syms = sorted(getattr(expr, "free_symbols", set()), key=lambda s: s.name)
    name = str(node.params.get("var", "")).strip()
    if name:
        for s in syms:
            if s.name == name:
                return s
        return sp.Symbol(name)
    if len(syms) == 1:
        return syms[0]
    if not syms:
        raise GraphValidationError(
            f"{node.type_id} {node.node_id!r}: в выражении нет переменной — "
            f"укажите параметр var или подключите вход var."
        )
    raise GraphValidationError(
        f"{node.type_id} {node.node_id!r}: в выражении несколько переменных "
        f"{[s.name for s in syms]} — укажите, по какой (параметр var)."
    )


# ---------- Источники ----------

_ASSUMPTIONS = ["complex", "real", "positive"]


class SymbolNode(Node):
    """Символьная переменная (x, y, z, …). Источник EXPR."""
    type_id = "symbol"
    category = "symbolic"
    display_name = "Символ"
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "x"},
        "assumptions": {"type": "enum", "values": _ASSUMPTIONS, "default": "complex"},
    }

    def validate_params(self) -> None:
        name = str(self.params.get("name", "")).strip()
        if not name:
            raise GraphValidationError(f"Узел {self.node_id!r}: пустое имя символа.")

    def compute(self, inputs, ctx: ExecContext):
        name = str(self.params.get("name", "x")).strip()
        syms = build_symbols([name], self.params.get("assumptions", "complex"))
        return {"out": syms[name]}


class ExprConstNode(Node):
    """
    Символьное выражение из текста (например, '(x+1)^2/(x-1)'). Источник EXPR.

    Имена переменных и их предположения берутся из параметров: vars — список
    имён, assumptions — общий режим (complex/real/positive). Часть имён можно
    использовать как плейсхолдеры коэффициентов ('a*x^2+b*x+c') и подставить в
    них случайные числа через вход values (NUMBER_DICT) — переменные, не попавшие
    в values, останутся символами.
    """
    type_id = "expr_const"
    category = "symbolic"
    display_name = "Выражение"
    description = ("Выражение из текста; буквы — переменные/коэффициенты. Вход "
                   "values (NUMBER_DICT) подставляет случайные числа. Выход: EXPR.")
    INPUTS = [Port("values", PortType.NUMBER_DICT, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "expr": {"type": "string", "default": "x"},
        "vars": {"type": "list", "default": [], "optional": True},
        "assumptions": {"type": "enum", "values": _ASSUMPTIONS, "default": "complex"},
    }

    def validate_params(self) -> None:
        # Разбираем на этапе валидации, чтобы поймать опечатки в редакторе.
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        parse_expr(self.params.get("expr", ""), syms)

    def compute(self, inputs, ctx: ExecContext):
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        expr = parse_expr(self.params.get("expr", ""), syms)
        return {"out": substitute_values(expr, inputs.get("values"))}


class RandomPolynomialNode(Node):
    """
    Случайный многочлен заданной степени с целыми коэффициентами. Источник EXPR.

    Параметры: var (имя переменной), degree (степень), min/max (диапазон
    коэффициентов). Старший коэффициент гарантированно ненулевой (степень точная).
    Воспроизводимость — через ctx.rng (как у random_natural).
    """
    type_id = "random_polynomial"
    category = "symbolic"
    display_name = "Случайный многочлен"
    description = ("Случайный многочлен степени degree с целыми коэффициентами "
                   "из [min;max]. Выход: EXPR.")
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "var": {"type": "string", "default": "x"},
        "degree": {"type": "int", "default": 2},
        "min": {"type": "int", "default": -5, "optional": True},
        "max": {"type": "int", "default": 5, "optional": True},
    }

    def validate_params(self) -> None:
        try:
            if int(self.params.get("degree", 2)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: degree должно быть целым ≥ 0."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        x = sp.Symbol(str(self.params.get("var", "x")))
        deg = int(self.params.get("degree", 2))
        lo = int(self.params.get("min", -5))
        hi = int(self.params.get("max", 5))
        rng = ctx.rng
        terms = []
        for k in range(deg + 1):
            c = rng.randint(lo, hi)
            if k == deg and c == 0:
                # Старший коэффициент не должен быть нулём (иначе степень падает).
                c = hi if hi != 0 else 1
            terms.append(c * x ** k)
        return {"out": sp.Add(*terms)}


# ---------- Алгебраические преобразования (EXPR → EXPR) ----------

class _UnaryExprNode(Node):
    """База для операций над одним выражением. SYMPY_OP задаёт sympy-функцию."""
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    SYMPY_OP = "expand"   # имя метода/функции sympy

    def _apply(self, sp, expr):
        return getattr(sp, self.SYMPY_OP)(expr)

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        try:
            result = self._apply(sp, expr)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class ExpandNode(_UnaryExprNode):
    type_id = "expand"; display_name = "Раскрыть скобки"; SYMPY_OP = "expand"


class FactorNode(_UnaryExprNode):
    type_id = "factor"; display_name = "Разложить на множители"; SYMPY_OP = "factor"


class SimplifyNode(_UnaryExprNode):
    type_id = "simplify"; display_name = "Упростить"; SYMPY_OP = "simplify"


class TogetherNode(_UnaryExprNode):
    type_id = "together"; display_name = "Привести к общему знаменателю"
    SYMPY_OP = "together"


class CancelNode(_UnaryExprNode):
    type_id = "cancel"; display_name = "Сократить дробь"; SYMPY_OP = "cancel"


class TrigsimpNode(_UnaryExprNode):
    type_id = "trigsimp"; display_name = "Упростить тригонометрию"
    SYMPY_OP = "trigsimp"


class _ExprWithVarNode(Node):
    """База для операций «выражение + переменная» (collect, apart)."""
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"var": {"type": "string", "default": "", "optional": True}}
    SYMPY_OP = "collect"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        try:
            result = getattr(sp, self.SYMPY_OP)(expr, var)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class CollectNode(_ExprWithVarNode):
    type_id = "collect"; display_name = "Сгруппировать по степеням"
    SYMPY_OP = "collect"


class ApartNode(_ExprWithVarNode):
    type_id = "apart"; display_name = "Разложить на простейшие"; SYMPY_OP = "apart"


# ---------- Арифметика выражений ----------

_BINARY_OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b,
    "pow": lambda a, b: a ** b,
}


class ExprBinaryNode(Node):
    """Бинарная операция над двумя выражениями (+, −, ×, ÷, ^)."""
    type_id = "expr_binop"
    category = "symbolic"
    display_name = "Операция (выражения)"
    INPUTS = [Port("a", PortType.EXPR), Port("b", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": list(_BINARY_OPS), "default": "add"},
    }

    def validate_params(self) -> None:
        op = self.params.get("op", "add")
        if op not in _BINARY_OPS:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестная операция {op!r}. "
                f"Допустимы: {list(_BINARY_OPS)}"
            )

    def compute(self, inputs, ctx: ExecContext):
        a = as_expr(inputs["a"])
        b = as_expr(inputs["b"])
        try:
            result = _BINARY_OPS[self.params.get("op", "add")](a, b)
        except Exception as e:
            raise RetryGeneration(f"expr_binop {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class SubstituteNode(Node):
    """
    Подстановка значений в выражение: subs из NUMBER_DICT (имя→число).

    Выход — EXPR (символьный результат). Для финального числа используйте
    evaluate (EXPR → NUMBER).
    """
    type_id = "expr_subs"
    category = "symbolic"
    display_name = "Подстановка"
    INPUTS = [Port("in", PortType.EXPR), Port("values", PortType.NUMBER_DICT)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        values = inputs.get("values", {}) or {}
        mapping = {sp.Symbol(str(k)): v for k, v in values.items()}
        try:
            result = expr.subs(mapping)
        except Exception as e:
            raise RetryGeneration(f"expr_subs {self.node_id!r}: {e}")
        return {"out": result}


class EvaluateNode(Node):
    """
    Численная оценка выражения → NUMBER. Бросает RetryGeneration, если результат
    не вещественное число (остались символы, или вышло комплексное/inf/nan).
    """
    type_id = "expr_eval"
    category = "symbolic"
    display_name = "Вычислить (число)"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        try:
            val = sp.N(expr)
            if not val.is_number or val.is_real is False:
                raise ValueError(f"не вещественное число: {val}")
            f = float(val)
        except (TypeError, ValueError, AttributeError) as e:
            raise RetryGeneration(f"expr_eval {self.node_id!r}: {e}")
        import math
        if math.isinf(f) or math.isnan(f):
            raise RetryGeneration(f"expr_eval {self.node_id!r}: inf/nan.")
        return {"out": f}


# ---------- Математический анализ (diff / integrate / limit / series) ----------

def _parse_point(sp, raw):
    """
    Разобрать точку (число, 'oo', '-oo', 'pi', выражение) в sympy-объект.
    Некорректный ввод → RetryGeneration (а не утечка GraphValidationError из
    parse_expr) — узлы пределов/рядов/сумм зовут это вне своих try-блоков.
    """
    s = str(raw).strip()
    if s in ("oo", "+oo", "inf", "+inf"):
        return sp.oo
    if s in ("-oo", "-inf"):
        return -sp.oo
    try:
        return parse_expr(s)
    except GraphValidationError as e:
        raise RetryGeneration(f"Не удалось разобрать точку {raw!r}: {e}")


class DiffNode(Node):
    """
    Производная выражения по переменной. Порядок задаётся параметром order
    (по умолчанию 1). Вход var — символ (EXPR), по которому дифференцируем.
    """
    type_id = "diff"
    category = "symbolic"
    display_name = "Производная"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "order": {"type": "int", "default": 1},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def validate_params(self) -> None:
        try:
            if int(self.params.get("order", 1)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: order должен быть целым ≥ 0."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        order = int(self.params.get("order", 1))
        try:
            result = sp.diff(expr, var, order)
        except Exception as e:
            raise RetryGeneration(f"diff {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class IntegrateNode(Node):
    """
    Интеграл выражения по переменной. Если заданы пределы lower/upper —
    определённый интеграл, иначе — неопределённый (первообразная).
    Пределы допускают 'oo'/'-oo' и выражения.
    """
    type_id = "integrate"
    category = "symbolic"
    display_name = "Интеграл"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "lower": {"type": "string", "default": "", "optional": True},
        "upper": {"type": "string", "default": "", "optional": True},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        lo = str(self.params.get("lower", "")).strip()
        hi = str(self.params.get("upper", "")).strip()
        try:
            if lo and hi:
                result = sp.integrate(expr, (var, _parse_point(sp, lo),
                                             _parse_point(sp, hi)))
            else:
                result = sp.integrate(expr, var)
        except Exception as e:
            raise RetryGeneration(f"integrate {self.node_id!r}: {e}")
        # Неберущийся интеграл sympy возвращает как Integral(...) — это валидно
        # для показа, но численно бесполезно; оставляем как есть.
        return {"out": guard_numeric(result)}


class LimitNode(Node):
    """
    Предел выражения при var → point. Направление: '+', '-' или '+-' (двусторонний).
    point допускает 'oo'/'-oo' и выражения.
    """
    type_id = "limit"
    category = "symbolic"
    display_name = "Предел"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "point": {"type": "string", "default": "0"},
        "dir": {"type": "enum", "values": ["+-", "+", "-"], "default": "+-"},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        direction = self.params.get("dir", "+-")
        try:
            result = sp.limit(expr, var, point, direction)
        except Exception as e:
            raise RetryGeneration(f"limit {self.node_id!r}: {e}")
        return {"out": result}


class LimitDisplayNode(Node):
    """
    Невычисленный предел lim_{var→point} f (для условия задачи) → EXPR.
    Рендерится знаком предела; .doit() намеренно не вызывается — это аналог
    sum_display для сумм. Направление: '+', '-' или '+-'.
    """
    type_id = "limit_display"
    category = "symbolic"
    display_name = "Знак предела (lim)"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "point": {"type": "string", "default": "0"},
        "dir": {"type": "enum", "values": ["+-", "+", "-"], "default": "+-"},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        direction = self.params.get("dir", "+-")
        try:
            result = sp.Limit(expr, var, point, direction)
        except Exception as e:
            raise RetryGeneration(f"limit_display {self.node_id!r}: {e}")
        return {"out": result}


class SeriesNode(Node):
    """
    Разложение в ряд Тейлора около точки point до порядка order (член O(...)
    отбрасывается, остаётся многочлен). По умолчанию около 0 (ряд Маклорена).
    """
    type_id = "series"
    category = "symbolic"
    display_name = "Ряд Тейлора"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "point": {"type": "string", "default": "0"},
        "order": {"type": "int", "default": 6},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def validate_params(self) -> None:
        try:
            if int(self.params.get("order", 6)) < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: order должен быть целым ≥ 1."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        order = int(self.params.get("order", 6))
        try:
            result = sp.series(expr, var, point, order).removeO()
        except Exception as e:
            raise RetryGeneration(f"series {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


# ---------- Ряды (суммирование) ----------

class _SumBaseNode(Node):
    """
    База для узлов суммирования. Вход term:EXPR — общий член, index:EXPR —
    переменная суммирования (символ). Границы lower/upper из параметров
    (допускают 'oo'/'-oo'/выражения).
    """
    category = "symbolic"
    INPUTS = [Port("term", PortType.EXPR), Port("index", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "lower": {"type": "string", "default": "1"},
        "upper": {"type": "string", "default": "oo"},
    }

    def _bounds(self, sp, inputs):
        term = as_expr(inputs["term"])
        index = as_expr(inputs["index"])
        lo = _parse_point(sp, self.params.get("lower", "1"))
        hi = _parse_point(sp, self.params.get("upper", "oo"))
        return term, index, lo, hi


class SummationNode(_SumBaseNode):
    """Сумма ряда (вычисленная) → EXPR. Например, Σ 1/n² = π²/6."""
    type_id = "summation"
    display_name = "Сумма ряда"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        term, index, lo, hi = self._bounds(sp, inputs)
        try:
            result = sp.summation(term, (index, lo, hi))
        except Exception as e:
            raise RetryGeneration(f"summation {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class SumDisplayNode(_SumBaseNode):
    """
    Невычисленная сумма ∑ (для условия задачи) → EXPR. Рендерится как знак
    суммы с пределами; .doit() намеренно не вызывается.
    """
    type_id = "sum_display"
    display_name = "Знак суммы (∑)"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        term, index, lo, hi = self._bounds(sp, inputs)
        try:
            result = sp.Sum(term, (index, lo, hi))
        except Exception as e:
            raise RetryGeneration(f"sum_display {self.node_id!r}: {e}")
        return {"out": result}


class IsConvergentNode(Node):
    """
    Проверка сходимости ряда Σ term (index от lower до бесконечности) → BOOL.
    Использует sympy.Sum.is_convergent(). Если sympy не смог определить —
    RetryGeneration (неинформативный результат лучше пере-сгенерировать).
    """
    type_id = "is_convergent"
    category = "symbolic"
    display_name = "Ряд сходится?"
    INPUTS = [Port("term", PortType.EXPR), Port("index", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.BOOL)]
    PARAMS_SCHEMA = {"lower": {"type": "string", "default": "1"}}

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        term = as_expr(inputs["term"])
        index = as_expr(inputs["index"])
        lo = _parse_point(sp, self.params.get("lower", "1"))
        try:
            verdict = sp.Sum(term, (index, lo, sp.oo)).is_convergent()
        except Exception as e:
            raise RetryGeneration(f"is_convergent {self.node_id!r}: {e}")
        if verdict not in (sp.true, sp.false, True, False):
            raise RetryGeneration(
                f"is_convergent {self.node_id!r}: не удалось определить сходимость."
            )
        return {"out": bool(verdict)}


# ---------- ТФКП (комплексный анализ) ----------

class _ComplexUnaryNode(Node):
    """База для покомпонентных операций над комплексным выражением (EXPR→EXPR)."""
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    SYMPY_OP = "re"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        try:
            result = getattr(sp, self.SYMPY_OP)(expr)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": result}


class ReNode(_ComplexUnaryNode):
    type_id = "re"; display_name = "Действительная часть"; SYMPY_OP = "re"


class ImNode(_ComplexUnaryNode):
    type_id = "im"; display_name = "Мнимая часть"; SYMPY_OP = "im"


class ArgNode(_ComplexUnaryNode):
    type_id = "arg"; display_name = "Аргумент"; SYMPY_OP = "arg"


class AbsNode(_ComplexUnaryNode):
    type_id = "abs"; display_name = "Модуль"; SYMPY_OP = "Abs"


class ConjugateNode(_ComplexUnaryNode):
    type_id = "conjugate"; display_name = "Сопряжённое"; SYMPY_OP = "conjugate"


class ExpandComplexNode(_ComplexUnaryNode):
    type_id = "expand_complex"; display_name = "Разложить (a+bi)"
    SYMPY_OP = "expand_complex"


class ResidueNode(Node):
    """
    Вычет функции в точке (ядро ТФКП). Вход in:EXPR — функция, var:EXPR —
    комплексная переменная, point — точка (полюс; допускает выражения, oo).
    """
    type_id = "residue"
    category = "symbolic"
    display_name = "Вычет"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "point": {"type": "string", "default": "0"},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        try:
            result = sp.residue(expr, var, point)
        except Exception as e:
            raise RetryGeneration(f"residue {self.node_id!r}: {e}")
        return {"out": result}


class SolveNode(Node):
    """
    Решить уравнение expr = 0 относительно var; собрать корни в BLOCK_LIST
    (по одному FormulaBlock на корень). Удобно как готовый ответ задачи.

    Опционально prefix оборачивает каждый корень (например, 'z = …').
    """
    type_id = "solve"
    category = "symbolic"
    display_name = "Решить уравнение"
    INPUTS = [Port("in", PortType.EXPR),
              Port("var", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "prefix": {"type": "string", "default": "", "optional": True},
        "var": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        try:
            roots = sp.solve(expr, var)
        except Exception as e:
            raise RetryGeneration(f"solve {self.node_id!r}: {e}")
        prefix = str(self.params.get("prefix", "")).strip()
        blocks = []
        for r in roots:
            latex = to_latex(r)
            if prefix:
                latex = f"{prefix} = {latex}"
            blocks.append(FormulaBlock(latex))
        return {"out": blocks}


# ---------- Интегральные преобразования (Лаплас / Фурье) ----------

class _TransformNode(Node):
    """
    База для интегральных преобразований. Переменные оригинала и образа задаются
    параметрами from_var / to_var (по умолчанию t→s). Подкласс реализует _apply.
    """
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "from_var": {"type": "string", "default": "t", "optional": True},
        "to_var": {"type": "string", "default": "s", "optional": True},
    }
    DEFAULT_FROM = "t"
    DEFAULT_TO = "s"

    def _vars(self, sp, expr):
        # Переменную оригинала берём ИЗ выражения по имени (у неё могут быть
        # предположения, заданные источником) — иначе свежий Symbol не совпадёт
        # со свободной переменной и преобразование «не увидит» её.
        fv = str(self.params.get("from_var", self.DEFAULT_FROM)) or self.DEFAULT_FROM
        tv = str(self.params.get("to_var", self.DEFAULT_TO)) or self.DEFAULT_TO
        match = [sym for sym in getattr(expr, "free_symbols", set()) if sym.name == fv]
        a = match[0] if match else sp.Symbol(fv)
        return a, sp.Symbol(tv)

    def _apply(self, sp, expr, a, b):
        raise NotImplementedError

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        a, b = self._vars(sp, expr)
        try:
            result = self._apply(sp, expr, a, b)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": result}


class LaplaceNode(_TransformNode):
    """Преобразование Лапласа: f(t) → F(s) = L{f}. По умолчанию t→s."""
    type_id = "laplace"
    display_name = "Преобразование Лапласа"
    DEFAULT_FROM = "t"; DEFAULT_TO = "s"

    def _apply(self, sp, expr, t, s):
        return sp.laplace_transform(expr, t, s, noconds=True)


class InverseLaplaceNode(_TransformNode):
    """Обратное преобразование Лапласа: F(s) → f(t). По умолчанию s→t."""
    type_id = "inverse_laplace"
    display_name = "Обратное преобр. Лапласа"
    DEFAULT_FROM = "s"; DEFAULT_TO = "t"

    def _apply(self, sp, expr, s, t):
        return sp.inverse_laplace_transform(expr, s, t)


class FourierNode(_TransformNode):
    """Преобразование Фурье: f(x) → F(ω). По умолчанию x→omega."""
    type_id = "fourier"
    display_name = "Преобразование Фурье"
    DEFAULT_FROM = "x"; DEFAULT_TO = "omega"

    def _apply(self, sp, expr, x, w):
        return sp.fourier_transform(expr, x, w)


class InverseFourierNode(_TransformNode):
    """Обратное преобразование Фурье: F(ω) → f(x). По умолчанию omega→x."""
    type_id = "inverse_fourier"
    display_name = "Обратное преобр. Фурье"
    DEFAULT_FROM = "omega"; DEFAULT_TO = "x"

    def _apply(self, sp, expr, w, x):
        return sp.inverse_fourier_transform(expr, w, x)


# ---------- Рендер ----------

class ExprBlockNode(Node):
    """
    Формульный блок из символьного выражения (EXPR → BLOCK).

    Опционально оборачивает выражение в равенство 'prefix = expr' (например,
    'f(x) = ...'), если задан параметр prefix.
    """
    type_id = "expr_block"
    category = "symbolic"
    display_name = "Формульный блок"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "prefix": {"type": "string", "default": "", "optional": True},
        "relation": {"type": "string", "default": "=", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        from .compute import _join_prefix
        expr = as_expr(inputs["in"])
        latex = _join_prefix(self.params.get("prefix", ""), to_latex(expr),
                             self.params.get("relation", "="))
        return {"out": FormulaBlock(latex)}
