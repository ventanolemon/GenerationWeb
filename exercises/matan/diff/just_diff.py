import random
import sympy as sp


def clear_latex(inp):
    inp = (inp.replace(r"\operatorname", "").replace(r"atan", "arctg").replace(r"asin", "arcsin").replace(r"acos", "arccos")
                 .replace(r"\tan", "tg").replace("log", "ln"))
    return inp


e = sp.Symbol("e")
def get_ev(res, ind=None, pw=False, sq=True, taboo=None):
    if taboo is None:
        taboo = list()

    a, m = random.randint(2, 10), random.randint(2, 10)
    step = random.randint(2, 5)
    base_equals = [sp.sin(res), sp.tan(res), sp.asin(res), sp.atan(res), a ** res - m, sp.ln(m + res),
                   (e ** res) - m,
                   (step + res) ** m - a]

    if ind is not None:
        return base_equals[ind]

    equals_variants = [base_equals[i] for i in range(len(base_equals)) if i not in taboo]

    res_ev = random.choice(equals_variants)
    res_ind = base_equals.index(res_ev)
    if random.random() > 0.7 or pw:
        if (random.random() < 0.5 or not sq) and res_ev != sp.ln(m + res):
            res_ev **= step
        else:
            st = random.randint(2, 5)

            if st % 2 == 0 and res_ev != sp.ln(m + res):
                res_ev = res_ev ** 2 + step
            elif res_ev == sp.ln(m + res) and st % 2 == 0:
                st += 1

            root = sp.Rational(1, st)
            res_ev = res_ev ** root
    return res_ev, res_ind


def get_just_diff():
    x = sp.Symbol("x")
    const_1, const_2, const_3, const_4 = random.choices([i for i in range(-3, 6) if i], k=4)
    st_1, st_2, st_3, st_4 = random.choices([i for i in range(-2, 5) if i], k=4)
    first_x, second_x, third_x, fourth_x = (const_1 * x ** st_1, const_2 * x ** st_2, const_3 * x ** st_3,
                                            const_4 * x ** st_4)

    pws = [True, False, False]
    random.shuffle(pws)
    pw_1, pw_2, pw_3 = pws
    sqs = [True, False, False]
    random.shuffle(sqs)
    sq_1, sq_2, sq_3 = sqs

    ev_1, ind_1 = get_ev(first_x, pw=pw_1, sq=sq_1)
    ev_2, ind_2 = get_ev(second_x, pw=pw_2, sq=sq_2, taboo=[ind_1])
    ev_3, ind_3 = get_ev(third_x, pw=pw_3, sq=sq_3, taboo=[ind_1, ind_2])

    if random.random() < 0.92:
        res_ev = ev_1 * ev_2 + ev_3  # / ev_4

        answer = sp.diff(res_ev, x)
    else:
        osn = random.randint(2, 10)
        res_ev = osn ** (ev_1 * ev_2 + ev_3)

        answer = sp.diff(res_ev, x)

    res_latex = ("y=" + clear_latex(sp.latex(res_ev)))
    ans_latex = clear_latex(sp.latex(answer))
    return (("text", " 1.\tВычислить производную функции\n"),
            ("formula", res_latex),
            ("formula", ans_latex))


if __name__ == "__main__":
    res = get_just_diff()
    print(res[0][1])
    print(res[1][1])
    # x = sp.Symbol("x")
    # print(sp.latex(sp.real_root(sp.sin(x), 5)))