import random
import sympy as sp


def clear_latex(inp):
    inp = (inp.replace(r"\operatorname", "").replace(r"atan", "arctg").replace(r"asin", "arcsin").replace(r"acos", "arccos")
                 .replace(r"\tan", "tg").replace("log", "ln"))
    return inp


e = sp.Symbol("e")
def get_ev(res, ind=None):
    a, m = random.randint(2, 10), random.randint(2, 10)
    base_equals = [sp.sin(res), sp.tan(res), sp.asin(res), sp.atan(res), m + a ** res, sp.ln(1 + res),
                   (1 + res) ** m]
    if ind is not None:
        return base_equals[ind]
    return random.choice(base_equals)


def get_ln_secret_diff():
    x = sp.Symbol("x")
    const_1 = random.choices([i for i in range(-3, 6) if i], k=1)[0]
    st_1 = random.choices([i for i in range(-2, 5) if i], k=1)[0]
    first_x = const_1 * x ** st_1
    ev_1 = get_ev(first_x)

    osn_ev = get_ev(x)
    res_ev = osn_ev ** ev_1
    answer = sp.diff(res_ev, x)

    res_latex = "y=(" + clear_latex(sp.latex(osn_ev)) + ")^{" + clear_latex(sp.latex(ev_1)) + "}"
    ans_latex = clear_latex(sp.latex(answer))
    return (("text", " 3.\tВычислить производную функции\n"),
            ("formula", res_latex),
            ("formula", ans_latex))
# {sin(x)}^{3x+1}
if __name__ == "__main__":
    res = get_ln_secret_diff()
    print(res[0][1])
    print(res[1][1])

