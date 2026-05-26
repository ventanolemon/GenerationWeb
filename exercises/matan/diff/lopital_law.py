import random
import sympy as sp


def clear_latex(inp):
    inp = (inp.replace(r"\operatorname", "").replace(r"atan", "arctg").replace(r"asin", "arcsin").replace(r"acos", "arccos")
                 .replace(r"\tan", "tg").replace("log", "ln"))  # .replace(r"\ln{\left(e\right)}", "").replace(r"\ln{\left(e \right)}", "")
    return inp


e = sp.E
def get_ev_zero(res, ind=None):
    a, m = random.randint(2, 10), random.randint(2, 5)
    base_equals = [(a ** res) - 1, sp.ln(1 + res),
                   (e ** res) - 1,
                   ((1 + res) ** m) - 1]  # , res ** a
    if ind is not None:
        return base_equals[ind]
    return random.choice(base_equals)

def get_ev_one(res, ind=None):
    a, m = random.randint(2, 10), random.randint(2, 10)
    base_equals = [sp.asin(a * res), sp.atan(a * res), sp.atan(a * res) ** 2, sp.acot(a * res) ** 2, a ** res,
                   (e ** (a * res)),
                   (1 + res) ** m]
    if ind is not None:
        return base_equals[ind]
    return random.choice(base_equals)


def get_lopital_law():
    x = sp.Symbol("x")
    const_1, const_2, const_3, const_4 = random.choices([i for i in range(6) if i], k=4)
    st_1, st_2, st_3, st_4 = 1, 1, 1, 1#  random.choices([i for i in range(5) if i], k=4)
    first_x, second_x, third_x, fourth_x = (const_1 * x ** st_1, const_2 * x ** st_2, const_3 * x ** st_3,
                                            const_4 * x ** st_4)
    ids_1 = random.sample(range(4), k=2)  # в range кол-во возможных выражений из get_ev_zero
    ids_2 = random.sample(range(4), k=2)  # в range кол-во возможных выражений из get_ev_zero
    # print(ids_2)
    ev_1, ev_2, ev_3, ev_4 = (get_ev_zero(first_x, ids_1[0]), get_ev_zero(second_x, ids_1[1]),
                              get_ev_zero(third_x, ids_2[0]), get_ev_zero(fourth_x, ids_2[1]))

    # print(ev_1, "----", ev_2)
    # print(ev_3, "----", ev_4)

    res_ev = (ev_1 + ev_2) / (ev_3 - ev_4)
    # print("----")
    # print(ev_1, ev_2, ev_3, ev_4)

    answer = sp.limit(res_ev, x, 0)
    return (("text", " 7.\tВычислить предел с помощью правила Лопиталя\n"),
            ("formula", r"\lim_{x \to 0} {" + clear_latex(sp.latex(res_ev)) + "}"),
            ("formula", clear_latex(sp.latex(answer))))


if __name__ == "__main__":
    res = get_lopital_law()
    print(res[0][1])
    print(res[1][1])
