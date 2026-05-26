import random
import sympy as sp


def get_2_perfect():
    x = sp.Symbol("x")

    a0, b0 = random.randint(-2, 9), random.choice([-2, -1, 1, 2, 3])
    a2, b2, c2 = *random.choices([-2, -1, 1, 2, 3, 4, 5], k=2), random.randint(-2, 4)
    c0, c1 = random.sample(range(-2, 6), k=2)
    k = random.choice([-2, -1, 1, 2, 3])

    zero_ev = (a0 * x ** 2 + b0 * x + c0) * k
    first_ev = (a0 * x ** 2 + b0 * x + c1) * k

    second_ev = a2 * x ** 2 + b2 * x + c2
    # if random.randint(0, 2):
    #     to = sp.oo
    # else:
    #     to = 0
    to = sp.oo
    if random.randint(0, 2):
        result = (zero_ev / first_ev) ** second_ev
    else:
        result = (first_ev / zero_ev) ** second_ev
    res = r"\lim_{x \to \infty} {" + sp.latex(result) + "}"
    return ("formula", res),  ("formula", sp.latex(sp.limit(result, x, sp.oo)))


if __name__ == "__main__":
    print(get_2_perfect()[0].replace(r"\\", '\\'))
