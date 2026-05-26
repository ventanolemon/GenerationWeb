import sympy as sp
import random

# Символы: y — обычная переменная (для отображения), но при дифф-нии — функция от x
x = sp.Symbol('x')
y = sp.Symbol('y')  # ← для LaTeX: просто y


def clean_latex_for_word(latex_str):
    """Подготавливает LaTeX для Word (OMaths)"""
    s = latex_str
    s = s.replace(r"^ {", r"^{").replace(r"^  {", r"^{")
    s = s.replace(r"_ {", r"_{").replace(r"_  {", r"_{")
    s = s.replace(r"\left", "").replace(r"\right", "")
    s = (s
         .replace(r"\operatorname{atan}", "arctg")
         .replace(r"\atan", "arctg")
         .replace(r"\arctan", "arctg")
         .replace(r"\asin", "arcsin")
         .replace(r"\acos", "arccos")
         .replace(r"\tan", "tg")
         .replace(r"\log", "ln")
         .replace(r"E", "e")
         .replace(r"\mathrm{e}", "e")
         .replace(r"\mathit{e}", "e")
         .replace(r"y\left(x\right)", "y")  # на случай
         )
    s = s.replace(r" \, ", " ").replace(r"\,", " ")
    return s.strip()


# Базовые простые выражения — как в исходном коде (без трансцендентных функций)
# y-содержащие (для 2 слагаемых)
y_based = [
    y,
    -y,
    2*y,
    -2*y,
    sp.Rational(1, 2)*y,
    y**2,
    -y**2,
    x*y,
    -x*y,
    x**2 * y,
    -x**2 * y,
    y / (x + 1),      # в исходнике было — оставляем (осторожно!)
    x / (y + 1),      # тоже было — но теперь y — символ, так что при дифф-нии будет безопасно
]

# x-содержащие (только x, без y — для 1 слагаемого)
x_based = [
    x,
    -x,
    2*x,
    -2*x,
    sp.Rational(1, 2)*x,
    x**2,
    -x**2,
    x**3,
    -x**3,
    x / 2,
]

# Константы
constants = [
    1, -1, 2, -2, 3, -3, sp.Rational(1, 2), -sp.Rational(1, 2), 0
]
def safe_rand_expr(attempts=5):
    """Генерирует "безопасное" случайное выражение, избегая явных ошибок."""
    basic_expressions = [
        x * y,
        x / y,
        y / x,
        x ** 2 * y,
        x ** 3 * y,
        y ** 3 * x,
        sp.sqrt(x) * y,
        sp.sqrt(y) * x,
        x / (y + 1),
        y / (x + 1),
    ]

    for _ in range(attempts):
        base = random.choice(basic_expressions)
        try:
            expr = base  # func(base)
            # Проверка на наличие явных ошибок (например, деление на 0)
            if expr.has(sp.zoo) or expr.has(sp.nan):
                continue
            # print(expr)
            return expr
        except Exception:
            continue
    # Если всё провалилось — возвращаем простое выражение
    return x + y


def generate_implicit_term(n_terms=2):
    """Генерирует неявное уравнение F(x, y) = 0."""
    terms = []
    for _ in range(n_terms):
        coeff = random.choice([1, -1, 2, -2, sp.Rational(1, 2), sp.Rational(3, 2)])
        expr = safe_rand_expr()
        terms.append(coeff * expr)
    F = sum(terms)
    if y not in F.free_symbols:
        return generate_implicit_term(n_terms=2)
    return F  # sp.simplify(F)


def generate_implicit_eq():
    """Генерирует F(x, y) = 0 с 2*y-членами, 1*x-членом, 1 константой."""
    # Выбираем 2 слагаемых с y
    term_y1 = generate_implicit_term()
    # 1 слагаемое только с x
    term_x = random.choice(x_based)
    # 1 константа
    term_c = random.choice(constants)

    # Собираем и упрощаем
    F = term_y1 + term_x + term_c
    return F


def implicit_derivative(F):
    """Вычисляет dy/dx из F(x, y) = 0."""
    # Временно используем y(x) для дифференцирования
    y_func = sp.Function('y')(x)
    F_sub = F.subs(y, y_func)
    dFdx = sp.diff(F_sub, x)
    dFdy = sp.diff(F_sub, y_func)
    if sp.simplify(dFdy) == 0:
        return sp.nan
    dy_dx = -dFdx / dFdy
    # Заменяем y(x) → y в финальном выражении (для читаемости)
    dy_dx = dy_dx.subs(y_func, y)
    return sp.simplify(dy_dx)

def point_1_1(expr):
    value = expr.subs({x: 1, y: 1})
    return value


def get_neyawn_diff():
    F = generate_implicit_eq()
    dy_dx = implicit_derivative(F)

    ans_value = point_1_1(dy_dx)
    if ans_value == sp.zoo:
        return get_neyawn_diff()

    # Уравнение: F(x, y) = 0
    equation_latex = sp.latex(sp.Eq(F, 0))
    # Ответ: y' = ...
    y_prime = sp.Symbol("y'")
    answer_eq = sp.Eq(y_prime, dy_dx)
    answer_latex = sp.latex(answer_eq)

    res_latex = clean_latex_for_word(equation_latex)
    ans_latex = clean_latex_for_word(answer_latex)

    return (
        ("text", " 4.\tВычислить производную неявно заданной функции в точке M(1,1)\n"),
        ("formula", res_latex),
        ("formula", ans_latex + f" \\quad \\text{{значение в точке }} M(1,1) = {ans_value}")
    )


# Пример
if __name__ == "__main__":
    parts = get_neyawn_diff()
    for typ, content in parts:
        if typ == "formula":
            print("$$", content, "$$")
        else:
            print(content)