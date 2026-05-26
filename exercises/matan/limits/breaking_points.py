import random
import sympy as sp


def get_breaking_points():
    x = sp.Symbol("x")

    a0, a1, a2 = random.sample([i for i in range(-5, 6) if i != 0], k=3)
    ev_0 = x - a0
    ev_1 = x - a1
    ev_2 = x - a2

    k = random.randint(2, 9) / 10
    if k:  # random.randint(0, 1)
        expression = (ev_1 / (ev_1 * ev_2))
        res = "f(x)=" + str(k) + r"^{\frac{" + sp.latex(ev_1.expand()) + "}{" + sp.latex((ev_1 * ev_2).expand()) + "}}"
    else:
        expression = abs((ev_0 * ev_1)) / (ev_1 * ev_2)
        chisl = abs((ev_0 * ev_1)).expand()
        znam = (ev_1 * ev_2).expand()
        res = "f(x)=" + sp.latex(chisl / znam)

    lim_1_mn, lim_1_pl = sp.limit(expression, x , a1, "-"), sp.limit(expression, x , a1, "+")
    lim_2_mn, lim_2_pl = sp.limit(expression, x , a2, "-"), sp.limit(expression, x , a2, "+")

    if lim_1_mn == lim_1_pl and abs(lim_1_mn) != sp.oo and abs(lim_1_pl) != sp.oo:
        type_1 = "устранимая"
    elif lim_1_mn != lim_1_pl and abs(lim_1_mn) != sp.oo and abs(lim_1_pl) != sp.oo:
        type_1 = "1 рода"
    else:
        type_1 = "2 рода"

    if lim_2_mn == lim_2_pl:
        type_2 = "устранимая"
    elif lim_2_mn == lim_2_pl and abs(lim_2_mn) != sp.oo and abs(lim_2_pl) != sp.oo:
        type_2 = "1 рода"
    else:
        type_2 = "2 рода"
    answer = (f"x = {a1}, {type_1}\n"
              f"x = {a2}, {type_2}")
    return ("formula", res), ("text", answer)


if __name__ == "__main__":
    print(get_breaking_points())
