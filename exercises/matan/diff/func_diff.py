import sympy as sp
import random

# Символы
x = sp.Symbol('x')
y = sp.Function('y')(x)  # y зависит от x


def safe_rand_expr(attempts=5):
    """Генерирует "безопасное" случайное выражение, избегая явных ошибок."""
    basic_expressions = [
        x,
        y,
        x + y,
        x - y,
        x * y,
        x / y,
        y / x,
        x ** 2,
        y ** 2,
        x ** 3,
        y ** 3,
        sp.sqrt(x),
        sp.sqrt(y),
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
            expr = func(base)
            # Проверка на наличие явных ошибок (например, деление на 0)
            if expr.has(sp.zoo) or expr.has(sp.nan):
                continue
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
    return sp.simplify(F)


def implicit_derivative(F):
    """Вычисляет dy/dx из F(x, y(x)) = 0."""
    dFdx = sp.diff(F, x)
    dFdy = sp.diff(F, y)
    # Защита от деления на ноль
    if dFdy == 0:
        return sp.nan
    dy_dx = -dFdx / dFdy
    return sp.simplify(dy_dx)


def get_neyawn_diff(n_terms=3):
    """
    Генерирует задание на неявное дифференцирование.

    Возвращает:
        tuple: (latex_уравнения, latex_производной)
    """
    F = generate_implicit_eq(n_terms=n_terms)
    dy_dx = implicit_derivative(F)

    # Уравнение F(x, y) = 0
    equation_latex = sp.latex(sp.Eq(F, 0))
    derivative_latex = sp.latex(dy_dx)

    return equation_latex, derivative_latex


# Пример использования
if __name__ == "__main__":
    eq, ans = get_neyawn_diff(n_terms=3)
    print("Задание (LaTeX):")
    print(eq)
    print("\nОтвет (LaTeX):")
    print(ans)