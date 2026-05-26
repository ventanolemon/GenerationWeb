import random
import sympy as sp


def clear_latex(inp):
    inp = (inp
           .replace(r"\operatorname", "")
           .replace(r"atan", "arctg")
           .replace(r"asin", "arcsin")
           .replace(r"acos", "arccos")
           .replace(r"\tan", "tg")
           .replace("log", "ln")
           .replace(r"E", "e")
           .replace(r"\mathrm{e}", "e")
           .replace(r"\mathit{e}", "e")
           )
    return inp


def get_ln_diff(max_attempts=10):
    x = sp.Symbol("x")

    for _ in range(max_attempts):
        # === Числитель: (a1*x + b1)^p1 * (a2*x^2 + b2*x + c2)^p2 ===
        p1, p2 = random.sample(range(1, 6), k=2)
        a1, a2 = random.sample([-3, -2, 2, 3, 4, 5, 6], k=2)

        b1 = random.choice([-4, -3, -2, 2, 3, 4, 5, 6, 7])
        term1 = (a1 * x + b1) ** p1

        b2 = random.choice([-3, -2, 2, 3, 4, 5, 6, 7])
        c2 = random.choice([-3, -2, 2, 3, 4, 5, 6, 7])
        quad = a2 * x**2 + b2 * x + c2
        # избегаем полных квадратов (иначе можно упростить)
        if sp.discriminant(quad, x) == 0:
            c2 += 1
            quad = a2 * x**2 + b2 * x + c2
        term2 = quad ** p2


        # === Знаменатель: (a3*x + b3)^p3 * sqrt(a4*x^2 + b4*x + c4) ===
        p3 = random.randint(2, 4)
        a3, a4 = random.sample([2, 3, 4, 5, 6, 7], k=2)
        b3 = random.choice([-4, -3, -2, 2, 3, 4, 5, 6])
        term3 = (a3 * x + b3) ** p3

        b4 = random.choice([-3, -2, 2, 3, 4, 5, 6, 7, 8, 9])
        c4 = random.choice([-3, -2, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        quad2 = a4 * x**2 + b4 * x + c4
        if sp.discriminant(quad2, x) == 0:
            c4 += 1
            quad2 = a4 * x**2 + b4 * x + c4
        term4 = sp.sqrt(quad2)  # = (...)^{1/2}

        terms = [term1, term2, term3, term4]
        random.shuffle(terms)

        numer, denom = terms[0] * terms[1], terms[2] * terms[3]
        expr_base = numer / denom

        # === Общая степень: обязательно нетривиальная ===
        if random.random() > 0.5:
            st = random.randint(2, 10)
            root = sp.Rational(1, st)
            res_ev = expr_base ** root
        else:
            res_ev = expr_base

        base_latex = clear_latex(sp.latex(res_ev))
        res_latex = base_latex

        # === Производная ===
        try:
            answer = sp.diff(res_ev, x)
            # Упрощаем, но не слишком
            answer = sp.together(answer)  # оставляем в виде дроби
            if answer.has(sp.zoo) or answer.has(sp.nan):
                continue
        except Exception:
            continue

        ans_latex = clear_latex(sp.latex(answer))
        res_latex = "y = " + res_latex

        return (
            ("text", " 2.\tВычислить производную функции, используя логарифмическую производную\n"),
            ("formula", res_latex),
            ("formula", ans_latex)
        )

    # Если все попытки провалились — возвращаем "запасной" нетривиальный пример
    expr_base = ((2*x + 3)**3 * (x**2 - x + 2)) / ((-2*x + 1)**2 * sp.sqrt(3*x**2 + 2*x + 5))
    res_ev = expr_base ** sp.Rational(3, 4)
    res_latex = r"y = \left(\frac{(2x + 3)^{3}(x^{2} - x + 2)}{(-2x + 1)^{2}\sqrt{3x^{2} + 2x + 5}}\right)^{\frac{3}{4}}"
    answer = sp.diff(res_ev, x)
    ans_latex = clear_latex(sp.latex(sp.simplify(answer)))

    return (
        ("text", " 2.\tВычислить производную функции, используя логарифмическую производную\n"),
        ("formula", "y = " + res_latex),
        ("formula", ans_latex)
    )


# Пример использования
if __name__ == "__main__":
    parts = get_ln_diff()
    for typ, content in parts:
        if typ == "formula":
            print("$$", content, "$$")
        else:
            print(content)