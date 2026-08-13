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
            f"{node.node_ref()}: в выражении нет переменной — "
            f"укажите параметр var или подключите вход var."
        )
    raise GraphValidationError(
        f"{node.node_ref()}: в выражении несколько переменных "
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
            raise GraphValidationError(f"{self.node_ref()}: пустое имя символа.")

    def summary(self) -> str:
        return str(self.params.get("name", "x")).strip()

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

    def summary(self) -> str:
        return str(self.params.get("expr", "")).strip()

    def compute(self, inputs, ctx: ExecContext):
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        expr = parse_expr(self.params.get("expr", ""), syms)
        return {"out": substitute_values(expr, inputs.get("values"))}


class ParseExprNode(Node):
    """
    Разобрать СТРОКУ в символьное выражение в рантайме (STRING → EXPR).

    Дополняет expr_const (там выражение — фиксированный параметр): здесь текст
    приходит проводом, поэтому можно, выбрав строку случайно (random_choice),
    и подставить её в текст/условие как есть, И разобрать в EXPR для символьной
    математики ответа — без дублирования пулов. Имена трактуются как символы
    (assumptions — общий режим).
    """
    type_id = "parse_expr"
    category = "symbolic"
    display_name = "Строка → выражение"
    description = ("Разобрать строку в символьное выражение. Вход: text "
                   "(STRING). Выход: EXPR.")
    INPUTS = [Port("text", PortType.STRING)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "vars": {"type": "list", "default": [], "optional": True},
        "assumptions": {"type": "enum", "values": _ASSUMPTIONS, "default": "complex"},
    }

    def compute(self, inputs, ctx: ExecContext):
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        text = inputs.get("text")
        if text is None or str(text).strip() == "":
            raise RetryGeneration(f"{self.node_ref()}: пустая строка.")
        return {"out": parse_expr(str(text), syms)}


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
                f"{self.node_ref()}: degree должно быть целым ≥ 0."
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
# Синонимы-символы: пользователь пишет '+', а не вспоминает 'add'.
_BINARY_OP_ALIASES = {
    "+": "add", "-": "sub", "−": "sub", "*": "mul", "×": "mul", "·": "mul",
    "/": "div", "÷": "div", "^": "pow", "**": "pow",
}
# Глиф операции для отображения на теле узла (наглядность холста).
_BINARY_OP_GLYPHS = {"add": "+", "sub": "−", "mul": "×", "div": "÷", "pow": "^"}


#: Операции, у которых больше двух слагаемых осмысленны без порядка:
#: сложение и умножение ассоциативны и коммутативны, поэтому «a+b+c» —
#: одно действие, а не два, и рисовать его одним узлом честно.
#:
#: Вычитание, деление и степень сюда НЕ входят, и это решение, а не
#: недоделка. Деление двух выражений — это дробь, самая читаемая форма
#: записи; «дробь из трёх» превращается в многоэтажную, которая читается
#: хуже двух обычных. Степень правоассоциативна, вычитание — лево-, и в
#: обоих случаях порядок пришлось бы либо показывать на узле, либо
#: выбрать за автора молча.
_VARIADIC_OPS = ("add", "mul")


class ExprBinaryNode(Node):
    """Операция над выражениями (+, −, ×, ÷, ^); сумма и произведение — N входов."""
    type_id = "expr_binop"
    category = "symbolic"
    display_name = "Операция (выражения)"
    INPUTS = [Port("a", PortType.EXPR), Port("b", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": list(_BINARY_OPS), "default": "add"},
        "count": {"type": "int", "default": 2, "optional": True},
    }

    def _op(self) -> str:
        raw = str(self.params.get("op", "add")).strip()
        return _BINARY_OP_ALIASES.get(raw, raw)

    def _count(self) -> int:
        """
        Сколько входов. Больше двух допускается только у ассоциативных
        операций — см. `_VARIADIC_OPS`.
        """
        try:
            count = int(self.params.get("count", 2))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: 'count' должен быть целым.")
        if count < 2:
            raise GraphValidationError(
                f"{self.node_ref()}: операции нужно минимум два входа.")
        if count > 2 and self._op() not in _VARIADIC_OPS:
            raise GraphValidationError(
                f"{self.node_ref()}: у операции "
                f"{self._op()!r} входов ровно два. Больше двух бывает у "
                f"{', '.join(_VARIADIC_OPS)} — остальные зависят от порядка, "
                f"и деление двух выражений это дробь, а не звено цепочки.")
        return count

    def validate_params(self) -> None:
        if self._op() not in _BINARY_OPS:
            raise GraphValidationError(
                f"{self.node_ref()}: неизвестная операция "
                f"{self.params.get('op')!r}. Допустимы: {list(_BINARY_OPS)} "
                f"или символы {list(_BINARY_OP_ALIASES)}."
            )
        self._count()

    def input_ports(self):
        # Имена a, b, c… — чтобы двухвходовые графы, сохранённые раньше,
        # продолжали ссылаться на «a» и «b» теми же проводами.
        return [Port(chr(ord("a") + i), PortType.EXPR)
                for i in range(self._count())]

    def summary(self) -> str:
        # 1 символ → холст нарисует крупным глифом (как арифметика LabVIEW).
        glyph = _BINARY_OP_GLYPHS.get(self._op(), self._op())
        count = self._count()
        return glyph if count == 2 else f"{glyph} ×{count}"

    def compute(self, inputs, ctx: ExecContext):
        operation = _BINARY_OPS[self._op()]
        values = [as_expr(inputs[chr(ord("a") + i)])
                  for i in range(self._count())]
        try:
            result = values[0]
            for value in values[1:]:
                result = operation(result, value)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        return {"out": guard_numeric(result)}


class ExprLogNode(Node):
    """
    Логарифм с основанием: log_base(выражение).

    Единственная функция, у которой второй аргумент — не «настройка», а
    полноправное выражение: основание бывает и числом, и параметром
    задания, и результатом другого узла. Записать его внутрь текста
    (`expr_const` с «log(x, 3)») можно, но тогда основание перестаёт быть
    точкой графа — его нельзя ни сгенерировать случайно, ни переиспользовать.

    Основание берётся со входа `base`, а если провод не подключён — из
    одноимённого параметра. Пусто и там и там — натуральный логарифм.
    Тот же приём, что у `to_block.prefix`: динамический вход перекрывает
    статический параметр.
    """
    type_id = "expr_log"
    category = "symbolic"
    display_name = "Логарифм"
    description = ("Логарифм выражения по основанию. Вход: EXPR (аргумент), "
                   "EXPR (основание, необязательно). Пустое основание — "
                   "натуральный. Выход: EXPR.")
    INPUTS = [Port("in", PortType.EXPR),
              Port("base", PortType.EXPR, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"base": {"type": "string", "default": "", "optional": True}}

    def summary(self) -> str:
        base = str(self.params.get("base", "")).strip()
        return f"log_{base}" if base else "ln"

    def compute(self, inputs, ctx: ExecContext):
        argument = as_expr(inputs["in"])
        base = inputs.get("base")
        if base is None:
            raw = str(self.params.get("base", "")).strip()
            base = parse_expr(raw) if raw else None
        try:
            result = (sympy().log(argument) if base is None
                      else sympy().log(argument, as_expr(base)))
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        return {"out": guard_numeric(result)}


class ExprReduceNode(Node):
    """
    Свёртка СПИСКА выражений в одно: сумма или произведение всех элементов.

    Закрывает доминирующий паттерн матановских генераторов (см.
    exercises/matan/limits/equals.py: `options[1] * options[2] * options[3]`):
    сумма/произведение N выражений раньше требовали цепочку из N−1 связанных
    expr_binop — теперь это list_new/random_choice(count>1)/туннель цикла →
    ОДИН expr_reduce. Элементы приводятся as_expr (числа и строки — тоже
    выражения). Пустой список → RetryGeneration.
    """
    type_id = "expr_reduce"
    category = "symbolic"
    display_name = "Свёртка списка (Σ/Π)"
    description = ("Сумма или произведение ВСЕХ выражений списка одним узлом. "
                   "Вход: list (LIST из EXPR). Выход: EXPR.")
    INPUTS = [Port("list", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": ["add", "mul"], "default": "mul"},
    }

    def _op(self) -> str:
        raw = str(self.params.get("op", "mul")).strip()
        return _BINARY_OP_ALIASES.get(raw, raw)

    def validate_params(self) -> None:
        if self._op() not in ("add", "mul"):
            raise GraphValidationError(
                f"{self.node_ref()}: op должен быть add или mul "
                f"(или символы '+', '*')."
            )

    def summary(self) -> str:
        # 1 символ → крупный глиф на холсте.
        return "Σ" if self._op() == "add" else "Π"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        raw = inputs.get("list")
        items = list(raw) if isinstance(raw, (list, tuple)) else (
            [raw] if raw is not None else [])
        if not items:
            raise RetryGeneration(
                f"{self.node_ref()}: пустой список выражений."
            )
        try:
            exprs = [as_expr(v) for v in items]
            result = sp.Add(*exprs) if self._op() == "add" else sp.Mul(*exprs)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        return {"out": guard_numeric(result)}


class SubstituteNode(Node):
    """
    Полиморфная подстановка в выражение. Каждый символ, названный в параметре
    `vars`, получает отдельный вход (ANY) и заменяется поданным значением —
    числом ИЛИ другим выражением (EXPR). Запасной вход values (NUMBER_DICT)
    подставляет числа пачкой (совместимость и динамические наборы); именованные
    входы приоритетнее values.

    Так одно выражение подставляется в другое «в качестве переменной» — например
    композиция f∘g: in='sin(u)', vars=['u'], на вход u подан EXPR выражения g.
    Выход — EXPR; для финального числа используйте expr_eval.
    """
    type_id = "expr_subs"
    category = "symbolic"
    display_name = "Подстановка"
    description = ("Заменить переменные значениями: именованные входы (число ИЛИ "
                   "EXPR) по списку vars + запасной values (NUMBER_DICT). "
                   "Выход: EXPR.")
    # Статический фолбэк для safe_ports при некорректных params (см. document).
    INPUTS = [Port("in", PortType.EXPR),
              Port("values", PortType.NUMBER_DICT, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"vars": {"type": "list", "default": [], "optional": True}}

    def _names(self) -> list[str]:
        seen, out = set(), []
        for n in (self.params.get("vars") or []):
            s = str(n).strip()
            if s and s not in seen:
                seen.add(s); out.append(s)
        return out

    def summary(self) -> str:
        names = self._names()
        return " ".join(f"{n}:=●" for n in names) if names else ""

    def input_ports(self):
        ports = [Port("in", PortType.EXPR)]
        ports += [Port(n, PortType.ANY, required=False) for n in self._names()]
        ports.append(Port("values", PortType.NUMBER_DICT, required=False))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from ..symbolic import _num, subs_value
        sp = sympy()
        expr = as_expr(inputs["in"])
        # Символы ищем в выражении ПО ИМЕНИ (предположения могут различаться).
        free = {s.name: s for s in expr.free_symbols}

        def sym(name):
            return free.get(name, sp.Symbol(name))

        mapping = {}
        # 1) числовой словарь-пачка (запасной путь) — целые float → Integer.
        for k, v in (inputs.get("values") or {}).items():
            mapping[sym(str(k))] = _num(sp, v)
        # 2) именованные входы: число или выражение, приоритетнее values.
        for name in self._names():
            v = inputs.get(name)
            if v is not None:
                mapping[sym(name)] = subs_value(v)
        try:
            result = expr.subs(mapping)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        return {"out": result}


class ExprLambdaNode(Node):
    """
    Определение символьной функции: тело-выражение + список формальных
    параметров. Выход — FUNC, который зовётся узлом expr_call. Одну функцию можно
    подать в несколько вызовов (переиспользование), не пересобирая тело.

    Тело строится любыми символьными узлами (или задаётся expr_const) и подаётся
    на вход body; параметры (params) — имена символов тела, которые вызов будет
    заменять. Символы, не входящие в params, остаются свободными (константы/
    коэффициенты формы).
    """
    type_id = "expr_lambda"
    category = "symbolic"
    display_name = "Функция (определение)"
    description = ("Функция из тела-выражения и параметров (params). "
                   "Вход: body (EXPR). Выход: FUNC — зовётся expr_call.")
    INPUTS = [Port("body", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.FUNC)]
    PARAMS_SCHEMA = {"params": {"type": "list", "default": []}}

    def validate_params(self) -> None:
        names = self.params.get("params")
        if not isinstance(names, list) or not names:
            raise GraphValidationError(
                f"{self.node_ref()}: 'params' должен быть непустым списком "
                f"имён параметров функции."
            )
        if len(set(map(str, names))) != len(names):
            raise GraphValidationError(
                f"{self.node_ref()}: имена параметров не уникальны."
            )

    def summary(self) -> str:
        names = ", ".join(str(n).strip() for n in (self.params.get("params") or []))
        return f"f({names}) = ●" if names else ""

    def compute(self, inputs, ctx: ExecContext):
        from ..symbolic import GraphFunction
        body = as_expr(inputs["body"])
        params = tuple(str(n).strip() for n in (self.params.get("params") or []))
        return {"out": GraphFunction(params=params, body=body)}


class ExprCallNode(Node):
    """
    Вызов символьной функции (FUNC): подставляет аргументы в тело по имени
    параметра. Каждое имя, названное в параметре `args`, получает вход (ANY) и
    может быть числом ИЛИ выражением. Имена аргументов совпадают с параметрами
    функции. Выход — EXPR.
    """
    type_id = "expr_call"
    category = "symbolic"
    display_name = "Функция (вызов)"
    description = ("Вызвать функцию: аргументы (число ИЛИ EXPR) по списку args "
                   "подставляются в тело. Вход: func (FUNC). Выход: EXPR.")
    INPUTS = [Port("func", PortType.FUNC)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"args": {"type": "list", "default": []}}

    def _names(self) -> list[str]:
        seen, out = set(), []
        for n in (self.params.get("args") or []):
            s = str(n).strip()
            if s and s not in seen:
                seen.add(s); out.append(s)
        return out

    def summary(self) -> str:
        names = self._names()
        return f"f({', '.join(names)})" if names else "f(…)"

    def input_ports(self):
        ports = [Port("func", PortType.FUNC)]
        ports += [Port(n, PortType.ANY, required=False) for n in self._names()]
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from ..symbolic import GraphFunction
        func = inputs.get("func")
        if not isinstance(func, GraphFunction):
            raise RetryGeneration(
                f"{self.node_ref()}: на вход func подана не функция."
            )
        args = {name: inputs.get(name) for name in self._names()}
        try:
            result = func.call(args)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        return {"out": guard_numeric(result)}


class SubsExprNode(Node):
    """
    Подстановка ВЫРАЖЕНИЯ вместо символа: in[name := value] → EXPR.

    Дополняет expr_subs (тот подставляет только числа из NUMBER_DICT): здесь
    значением служит любой EXPR — так собираются шаблонные ответы с точными
    величинами («z = r·(cos φ + i·sin φ)» c r = 576, φ = π/3). Символ ищется
    в выражении по имени.
    """
    type_id = "subs_expr"
    category = "symbolic"
    display_name = "Подстановка выражения"
    description = ("Заменить символ name выражением value (EXPR в EXPR) — "
                   "шаблонные формулы с точными значениями. Вход: in, value "
                   "(EXPR). Выход: EXPR.")
    INPUTS = [Port("in", PortType.EXPR), Port("value", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"name": {"type": "string", "default": "w"}}

    def validate_params(self) -> None:
        if not str(self.params.get("name", "")).strip():
            raise GraphValidationError(
                f"{self.node_ref()}: пустое имя подставляемого символа."
            )

    def summary(self) -> str:
        return f"{str(self.params.get('name', 'w')).strip()} := ●"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        value = as_expr(inputs["value"])
        name = str(self.params.get("name", "w")).strip()
        free = {s.name: s for s in expr.free_symbols}
        sym = free.get(name, sp.Symbol(name))
        try:
            result = expr.subs(sym, value)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        import math
        if math.isinf(f) or math.isnan(f):
            raise RetryGeneration(f"{self.node_ref()}: inf/nan.")
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
                f"{self.node_ref()}: order должен быть целым ≥ 0."
            )

    def summary(self) -> str:
        order = int(self.params.get("order", 1))
        var = str(self.params.get("var", "")).strip() or "x"
        sup = {2: "²", 3: "³"}.get(order, f"^{order}" if order > 3 else "")
        return f"d{sup}/d{var}{sup}" if order != 1 else f"d/d{var}"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        order = int(self.params.get("order", 1))
        try:
            result = sp.diff(expr, var, order)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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

    def summary(self) -> str:
        lo = str(self.params.get("lower", "")).strip().replace("oo", "∞")
        hi = str(self.params.get("upper", "")).strip().replace("oo", "∞")
        var = str(self.params.get("var", "")).strip() or "x"
        rng = f"[{lo}; {hi}]" if lo and hi else ""
        return f"∫{rng} d{var}"

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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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

    def summary(self) -> str:
        var = str(self.params.get("var", "")).strip() or "x"
        point = str(self.params.get("point", "0")).strip().replace("oo", "∞")
        d = {"+": "⁺", "-": "⁻"}.get(self.params.get("dir", "+-"), "")
        return f"lim {var}→{point}{d}"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        direction = self.params.get("dir", "+-")
        try:
            result = sp.limit(expr, var, point, direction)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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

    def summary(self) -> str:
        var = str(self.params.get("var", "")).strip() or "x"
        point = str(self.params.get("point", "0")).strip().replace("oo", "∞")
        d = {"+": "⁺", "-": "⁻"}.get(self.params.get("dir", "+-"), "")
        return f"lim {var}→{point}{d}"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = _resolve_var(self, inputs, expr)
        point = _parse_point(sp, self.params.get("point", "0"))
        direction = self.params.get("dir", "+-")
        try:
            result = sp.Limit(expr, var, point, direction)
        except Exception as e:
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
                f"{self.node_ref()}: order должен быть целым ≥ 1."
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
        if verdict not in (sp.true, sp.false, True, False):
            raise RetryGeneration(
                f"{self.node_ref()}: не удалось определить сходимость."
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
            raise RetryGeneration(f"{self.node_ref()}: {e}")
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
    INPUTS = [Port("in", PortType.EXPR),
              Port("prefix", PortType.STRING, required=False)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "prefix": {"type": "string", "default": "", "optional": True},
        "relation": {"type": "string", "default": "=", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        from .compute import _join_prefix
        expr = as_expr(inputs["in"])
        # Префикс — вход (значение из графа) либо статический параметр.
        prefix = inputs.get("prefix")
        if prefix is None:
            prefix = self.params.get("prefix", "")
        latex = _join_prefix(prefix, to_latex(expr),
                             self.params.get("relation", "="))
        return {"out": FormulaBlock(latex)}
