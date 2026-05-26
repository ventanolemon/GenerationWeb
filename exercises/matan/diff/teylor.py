import random
import sympy as sp
from sympy import latex


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
         .replace(r"\sinh", "sh")
         .replace(r"\cosh", "ch")
         )
    # Убираем лишние пробелы вокруг операторов (иногда Word ругается)
    s = s.replace(r" \, ", " ").replace(r"\,", " ")
    return s.strip()


def get_taylor_limit_task():
    x = sp.symbols('x')
    a_sym, b_sym = sp.symbols('a b')

    templates_sympy = {
        2: {
            'numerator': [
                ('cos', 1 - sp.cos(a_sym * x)),
                ('ch', sp.cosh(a_sym * x) - 1),
                ('exp', sp.exp(a_sym * x) - 1 - a_sym * x),
                ('ln', sp.log(1 + a_sym * x) - a_sym * x)
            ],
            'denominator': [
                ('cos', 1 - sp.cos(b_sym * x)),
                ('ch', sp.cosh(b_sym * x) - 1),
                ('exp', sp.exp(b_sym * x) - 1 - b_sym * x),
                ('ln', sp.log(1 + b_sym * x) - b_sym * x)
            ]
        },
        3: {
            'numerator': [
                ('sin', sp.sin(a_sym * x) - a_sym * x),
                ('sh', sp.sinh(a_sym * x) - a_sym * x),
                ('exp', sp.exp(a_sym * x) - 1 - a_sym * x - (a_sym**2 * x**2)/2),
                ('ln', sp.log(1 + a_sym * x) - a_sym * x + (a_sym**2 * x**2)/2)
            ],
            'denominator': [
                ('sin', sp.sin(b_sym * x) - b_sym * x),
                ('sh', sp.sinh(b_sym * x) - b_sym * x),
                ('exp', sp.exp(b_sym * x) - 1 - b_sym * x - (b_sym**2 * x**2)/2),
                ('ln', sp.log(1 + b_sym * x) - b_sym * x + (b_sym**2 * x**2)/2)
            ]
        },
        4: {
            'numerator': [
                ('cos', 1 - sp.cos(a_sym * x) - (a_sym**2 * x**2)/2),
                ('ch', sp.cosh(a_sym * x) - 1 - (a_sym**2 * x**2)/2),
                ('exp', sp.exp(a_sym * x) - 1 - a_sym * x - (a_sym**2 * x**2)/2 - (a_sym**3 * x**3)/6)
            ],
            'denominator': [
                ('cos', 1 - sp.cos(b_sym * x) - (b_sym**2 * x**2)/2),
                ('ch', sp.cosh(b_sym * x) - 1 - (b_sym**2 * x**2)/2),
                ('exp', sp.exp(b_sym * x) - 1 - b_sym * x - (b_sym**2 * x**2)/2 - (b_sym**3 * x**3)/6)
            ]
        }
    }

    order = random.choice([2, 3, 4])
    num_options = templates_sympy[order]['numerator']
    den_options = templates_sympy[order]['denominator']

    num_idx = random.randint(0, len(num_options) - 1)
    num_func_name, num_expr_sym = num_options[num_idx]

    den_candidates = [i for i, (name, _) in enumerate(den_options) if name != num_func_name]
    den_idx = random.choice(den_candidates) if den_candidates else random.randint(0, len(den_options) - 1)
    den_func_name, den_expr_sym = den_options[den_idx]

    a_val, b_val = random.sample([1, 2, 3, 4], k=2)

    num_expr = num_expr_sym.subs(a_sym, a_val)
    den_expr = den_expr_sym.subs(b_sym, b_val)

    num_expr = sp.simplify(num_expr)
    den_expr = sp.simplify(den_expr)

    # Генерируем "сырой" LaTeX
    raw_num_latex = latex(num_expr)
    raw_den_latex = latex(den_expr)

    # ✅ ОЧИЩАЕМ ДЛЯ WORD
    clean_num = clean_latex_for_word(raw_num_latex)
    clean_den = clean_latex_for_word(raw_den_latex)

    limit_expr = rf"\lim_{{x \to 0}} {{\frac{{{clean_num}}}{{{clean_den}}}}}"
    # ✅ Очищаем и весь предел целиком (на случай, если появятся \left/\right в дроби)
    limit_expr_clean = clean_latex_for_word(limit_expr)

    # Вычисляем ответ
    limit_value = sp.simplify(sp.limit(num_expr / den_expr, x, 0))
    raw_answer_latex = latex(limit_value)
    clean_answer = clean_latex_for_word(raw_answer_latex)

    # print(limit_expr_clean, clean_answer)
    return (
        ("text", " 8.\tВычислить предел, используя разложения функций по формуле Тейлора\n"),
        ("formula", limit_expr_clean),   # ← теперь чистый для Word
        ("formula", clean_answer)        # ← тоже чистый
    )