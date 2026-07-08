"""
Узлы обыкновенных дифференциальных уравнений (категория ode).

ОДУ записывается «человеческой» нотацией со штрихами: y'' + y = sin(x).
Узел ode_const разбирает её в sympy.Eq (тип EXPR — уравнение это Basic),
ode_solve решает через dsolve (опц. с начальными условиями — задача Коши),
ode_classify показывает тип уравнения, ode_check проверяет решение.

sympy импортируется лениво (см. core.graph.symbolic): движок графа headless.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType
from ..symbolic import parse_ode, substitute_values, sympy, to_latex


class OdeConstNode(Node):
    """
    ОДУ из текста со штрихами (y' , y'' …). Источник EXPR (несёт sympy.Eq).
    Параметры func/var — имя искомой функции и независимой переменной.

    В уравнении можно использовать буквы-коэффициенты (например, y'' + k*y = 0)
    и подставить в них случайные числа через вход values (NUMBER_DICT) — так
    получается ОДУ со случайными параметрами.
    """
    type_id = "ode_const"
    category = "ode"
    display_name = "Уравнение (ОДУ)"
    description = ("ОДУ из текста со штрихами (y'' + k*y = 0). Вход values "
                   "(NUMBER_DICT) подставляет случайные коэффициенты. Выход: EXPR.")
    INPUTS = [Port("values", PortType.NUMBER_DICT, required=False)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "equation": {"type": "string", "default": "y'' + y = 0"},
        "func": {"type": "string", "default": "y", "optional": True},
        "var": {"type": "string", "default": "x", "optional": True},
    }

    def _fv(self):
        return (str(self.params.get("func", "y")), str(self.params.get("var", "x")))

    def validate_params(self) -> None:
        f, v = self._fv()
        parse_ode(self.params.get("equation", ""), f, v)

    def compute(self, inputs, ctx: ExecContext):
        f, v = self._fv()
        eq, _func, _var = parse_ode(self.params.get("equation", ""), f, v)
        return {"out": substitute_values(eq, inputs.get("values"))}


class OdeSolveNode(Node):
    """
    Решить ОДУ (dsolve) → EXPR (решение y(x) = …).

    Начальные условия (задача Коши) задаются параметром ics — список строк вида
    'y(0)=1', \"y'(0)=0\". Пусто — общее решение с константами C1, C2, …
    func/var должны совпадать с теми, что в уравнении.
    """
    type_id = "ode_solve"
    category = "ode"
    display_name = "Решить ОДУ"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "func": {"type": "string", "default": "y", "optional": True},
        "var": {"type": "string", "default": "x", "optional": True},
        "ics": {"type": "list", "default": [], "optional": True},
    }

    def _ics(self, sp, f, v):
        """Разобрать начальные условия 'y(0)=1', \"y'(0)=0\" в словарь для dsolve."""
        out = {}
        for raw in (self.params.get("ics") or []):
            s = str(raw).strip()
            if not s or "=" not in s:
                continue
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            lp, rp = lhs.find("("), lhs.find(")")
            if lp == -1 or rp == -1 or rp < lp:
                # Нет скобок с точкой — некорректное условие, пропускаем
                # (лучше игнорировать кривое НУ, чем уронить генерацию).
                continue
            try:
                rhs_val = sp.sympify(rhs.strip())
                point = sp.sympify(lhs[lp + 1: rp])
            except (sp.SympifyError, SyntaxError, TypeError):
                continue
            nprime = lhs.count("'")
            if nprime == 0:
                out[f(point)] = rhs_val
            else:
                out[f(v).diff(v, nprime).subs(v, point)] = rhs_val
        return out

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        eq = inputs["in"]
        f = sp.Function(str(self.params.get("func", "y")))
        v = sp.Symbol(str(self.params.get("var", "x")))
        try:
            ics = self._ics(sp, f, v)
            sol = sp.dsolve(eq, f(v), ics=ics) if ics else sp.dsolve(eq, f(v))
        except Exception as e:
            raise RetryGeneration(f"ode_solve {self.node_id!r}: {e}")
        if isinstance(sol, (list, tuple)):
            # Несколько решений — берём первое (детерминированно).
            if not sol:
                raise RetryGeneration(f"ode_solve {self.node_id!r}: нет решения.")
            sol = sol[0]
        return {"out": sol}


class OdeClassifyNode(Node):
    """Тип ОДУ (separable / 1st_linear / …) → BLOCK (первый, основной класс)."""
    type_id = "ode_classify"
    category = "ode"
    display_name = "Тип ОДУ"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "func": {"type": "string", "default": "y", "optional": True},
        "var": {"type": "string", "default": "x", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock
        sp = sympy()
        eq = inputs["in"]
        f = sp.Function(str(self.params.get("func", "y")))
        v = sp.Symbol(str(self.params.get("var", "x")))
        try:
            kinds = sp.classify_ode(eq, f(v))
        except Exception as e:
            raise RetryGeneration(f"ode_classify {self.node_id!r}: {e}")
        if not kinds:
            raise RetryGeneration(f"ode_classify {self.node_id!r}: тип не определён.")
        return {"out": TextBlock(kinds[0])}


class OdeCheckNode(Node):
    """
    Проверить, удовлетворяет ли решение уравнению (checkodesol) → BOOL.
    Входы equation:EXPR (ОДУ) и solution:EXPR (решение y(x)=…).
    """
    type_id = "ode_check"
    category = "ode"
    display_name = "Проверить решение ОДУ"
    INPUTS = [Port("equation", PortType.EXPR), Port("solution", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.BOOL)]
    PARAMS_SCHEMA = {
        "func": {"type": "string", "default": "y", "optional": True},
        "var": {"type": "string", "default": "x", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        eq = inputs["equation"]
        sol = inputs["solution"]
        f = sp.Function(str(self.params.get("func", "y")))
        v = sp.Symbol(str(self.params.get("var", "x")))
        try:
            ok, _residual = sp.checkodesol(eq, sol, func=f(v))
        except Exception as e:
            raise RetryGeneration(f"ode_check {self.node_id!r}: {e}")
        return {"out": bool(ok)}
