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


def get_ev(res, ind):
    # print(res)
    base_equals = [sp.sin(res), sp.tan(res), sp.ln(1 + res)]  # sp.asin(res), sp.atan(res)
    return base_equals[ind]

def get_c_k_equals():
    x = sp.Symbol("x")
    res = x

    c0, k = random.randint(1, 4), random.randint(1, 5)
    # print(c0, k)
    # a, m = random.randint(2, 10), random.randint(2, 10)
    # cool_equals = [1 - sp.cos(res), a ** res - 1, (1 + res) ** m - 1]
    ind_1, ind_2 = random.sample(range(0, 3), 2)
    # print(c0, k)
    zero_ev, first_ev = get_ev(x ** k, ind_1), get_ev(res * c0, ind_2)

    c_e = random.randint(0, 2)
    if c_e == 0:
        second_ev = 1 - sp.cos(zero_ev)
        c0 = sp.Pow(2, sp.Rational(1, 2 * k)) / c0
        k = sp.Rational(1, 2 * k)
    elif c_e == 1:
        a = random.randint(2, 5)
        second_ev = a ** zero_ev - 1
        second_ev, first_ev = first_ev, second_ev
        c0 = c0 ** k / sp.ln(a)
    else:
        m = random.randint(2, 5)
        second_ev = (1 + first_ev) ** m - 1
        second_ev, first_ev = second_ev, zero_ev
        c0 = m ** k * c0 ** k
    # print(first_ev, second_ev, c0, k)
    res_C = r"\alpha(x)=C(" + sp.latex(first_ev) +  ")"
    res_k = r"  и    β(x)=(" + sp.latex(second_ev) + ")^k"
    res = clear_latex(res_C + res_k)
    # print(first_ev, "^k", sep="")
    return ("formula", res),  ("text", f"C={c0}, k={k}")


if __name__ == "__main__":
    print(get_c_k_equals())
