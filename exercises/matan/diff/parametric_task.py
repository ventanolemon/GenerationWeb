import random
import sympy as sp
from sympy import pi, E as e


def clean_latex_for_word(latex_str):
    r"""Подготавливает LaTeX для Word (OMaths): без пробелов в степенях, без \left\right и т.д."""
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


def generate_term(t):
    coeff = random.choice([-3, -2, -1, 1, 2, 3])
    k = random.randint(1, 2)
    m = random.randint(1, 2)
    deg = random.randint(1, 2)

    terms = [
        coeff * t ** deg,
        coeff * sp.sin(k * t),
        coeff * sp.cos(k * t),
        coeff * sp.exp(-m * t),
    ]
    # Комбинированные термы (умеренно)
    if random.random() < 0.35:
        terms += [
            coeff * sp.exp(-m * t) * sp.sin(k * t),
            coeff * sp.exp(-m * t) * sp.cos(k * t),
        ]
    return random.choice(terms)


def generate_expression(t, t0):
    # 2–3 терма + константа с вероятностью 60%
    n = random.randint(2, 3)
    expr = sum(generate_term(t) for _ in range(n))
    if expr.subs({t:t0}):
        expr -= expr.subs({t:t0})
        # expr += random.randint(-3, 3)

    if t not in expr.free_symbols:
        return sp.simplify(generate_expression(t, t0))
    return sp.simplify(expr)


def get_parametric_task(max_attempts=20):
    """Возвращает system_latex в формате \\cases{x = ... @ y = ...} и answer_latex"""
    t = sp.symbols('t')
    t0 = random.choice((pi / 2, pi, 2 * pi, 0))

    for _ in range(max_attempts):
        # try:
            x = generate_expression(t, t0)
            y = generate_expression(t, t0)

            dx = sp.diff(x, t)
            dy = sp.diff(y, t)

            # Проверка знаменателя ≠ 0
            if abs(dx.subs(t, t0).evalf()) < 1e-8:
                continue

            dy_dx = sp.simplify(dy / dx)
            result = sp.simplify(dy_dx.subs(t, t0))

            # Получаем LaTeX без $...$
            x_latex = clean_latex_for_word(sp.latex(x))
            y_latex = clean_latex_for_word(sp.latex(y))

            system_latex = (r"\left\{\matrix{ "  +
                            "x(t) = " + x_latex +
                            r"\\" +
                            "y(t) = " + y_latex +
                            r"\\}\right.")

            # Очистка для Word
            answer_latex = clean_latex_for_word(sp.latex(result))

            return (("text", f" 5.\tВычислить производную функции, заданной параметрически в точке {str(t0).replace("pi", "π")}.\n"),
                    ("formula", system_latex),
                    ("formula", answer_latex))


# Пример использования
if __name__ == "__main__":
    task, system, answer = get_parametric_task()
    print("СИСТЕМА УРАВНЕНИЙ:\n", system)
    print("\nОТВЕТ:\n", answer)
    #             return ("formula", system_latex), ("formula", answer_latex)
