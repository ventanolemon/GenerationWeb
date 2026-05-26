import random
import sympy as sp


def get_ev(res, ind=None):
    a, m = random.randint(2, 10), random.randint(2, 10)
    base_equals = [sp.sin(res), sp.tan(res), sp.asin(res), sp.atan(res), a ** res - 1, sp.ln(1 + res),
                   # (sp.exp ** res) - 1,
                   (1 + res) ** m - 1]
    if ind is not None:
        return base_equals[ind]
    return random.choice(base_equals)


def get_easy_equals():
    x = sp.Symbol("x")
    # e = sp.Symbol("e")
    a0, m0 = random.randint(2, 10), random.randint(2, 10)
    base_equals_x = [sp.sin(x), sp.tan(x), sp.asin(x), sp.atan(x), a0 ** x - 1, sp.ln(1 + x),
                   # (sp.exp ** res) - 1,
                   (1 + x) ** m0 - 1]
    options = list()
    options.extend(random.sample(base_equals_x, k=2))

    inner_equals = random.sample(base_equals_x, 3)
    outer_equals = random.sample(range(7), k=3)
    for i in range(2):
        options.append(get_ev(inner_equals[i], ind=outer_equals[i]))

    # options.append(get_ev(get_ev(inner_equals[2], ind=outer_equals[2])))
    res = x

    rnd = random.randint(0, 1)
    cool_part = 1 - sp.cos(res) if rnd else (1 / sp.sin(res)) - (1 / sp.tan(res))
    zero_ev = options[1] * options[2]

    if rnd == 0:
        first_ev = cool_part * options[0]
    else:
        first_ev = cool_part
    result = zero_ev / first_ev
    result_ans = sp.limit(result, x, 0)
    res = r"\lim_{x \to 0} {" + sp.latex(result) + "}"
    res = (res.replace("operatorname{asin}", "arcsin").replace("\operatorname{atan}", "arctg")
           .replace(r"\tan", "tg").replace(r"\log", "\ln"))
    return ("formula", res),  ("formula", sp.latex(result_ans))


if __name__ == "__main__":
    print(get_easy_equals())
