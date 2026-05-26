import sympy as sp
import random


# Символы
x = sp.Symbol('x')
y = sp.Function('y')(x)  # y зависит от x


def clean_latex_for_word(latex_str):
    """Подготавливает LaTeX для Word (OMaths): без пробелов в степенях, без \left\right и т.д."""
    s = latex_str
    # Удаляем пробелы после ^ и _ (главная причина ошибки -2147467263)
    s = s.replace(r"^ {", r"^{").replace(r"^  {", r"^{")
    s = s.replace(r"_ {", r"_{").replace(r"_  {", r"_{")
    # Убираем \left, \right — Word их не любит в BuildUp
    s = s.replace(r"\left", "").replace(r"\right", "")
    # Замена функций на школьные
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
         )
    # Убираем лишние пробелы вокруг операторов (иногда Word ругается)
    s = s.replace(r" \, ", " ").replace(r"\,", " ")
    return s.strip()


def safe_rand_expr(attempts=5):
    """Генерирует "безопасное" случайное выражение, избегая явных ошибок."""
    basic_expressions = [
        x + y,
        x - y,
        x * y,
        x / y,
        y / x,
        x ** 2 * y,
        y ** 2,
        x ** 3 * y,
        y ** 3 * x,
        sp.sqrt(x) * y,
        sp.sqrt(y) * x,
        x / (y + 1),
        y / (x + 1),
        (x + y) / (x - y + 1),
    ]

    functions = [
        lambda z: z,
        sp.exp,
        sp.sin,
        sp.cos,
        lambda z: sp.log(z + 1),  # +1 чтобы избежать log(0)
        lambda z: sp.sqrt(z + 1),  # +1 чтобы избежать sqrt(отриц.)
    ]

    for _ in range(attempts):
        base = random.choice(basic_expressions)
        func = random.choice(functions)
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


def generate_implicit_eq(n_terms=2):
    """Генерирует неявное уравнение F(x, y) = 0."""
    terms = []
    for _ in range(n_terms):
        coeff = random.choice([1, -1, 2, -2, sp.Rational(1, 2), sp.Rational(3, 2)])
        expr = safe_rand_expr()
        terms.append(coeff * expr)
    F = sum(terms)
    return F  # sp.simplify(F)


def implicit_derivative(F):
    """Вычисляет dy/dx из F(x, y(x)) = 0."""
    dFdx = sp.diff(F, x)
    dFdy = sp.diff(F, y)
    # Защита от деления на ноль
    if dFdy == 0:
        return sp.nan
    dy_dx = -dFdx / dFdy
    return dy_dx  # sp.simplify(dy_dx)


def get_neyawn_diff(n_terms=3):
    """
    Генерирует задание на неявное дифференцирование.

    Возвращает:
        tuple: (latex_уравнения, latex_производной)
    """
    global y

    F = generate_implicit_eq(n_terms=n_terms)
    dy_dx = implicit_derivative(F)

    y_prime = sp.Symbol("y")
    answer_eq = sp.Eq(dy_dx, 0)
    answer_latex = sp.latex(answer_eq)

    # Уравнение F(x, y) = 0
    equation_latex = sp.latex(sp.Eq(F, 0))
    # derivative_latex = sp.latex(dy_dx)
    y = y_prime
    res_latex = clean_latex_for_word(equation_latex)
    ans_latex = clean_latex_for_word(answer_latex)

    return (("text", " 4.\tВычислить производную неявно заданной функции\n"),
            ("formula", res_latex),
            ("formula", ans_latex))


# Пример использования
if __name__ == "__main__":
    eq, ans = get_neyawn_diff(n_terms=3)
    print("Задание (LaTeX):")
    print(eq)
    print("\nОтвет (LaTeX):")