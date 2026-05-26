import random
import sympy as sp


def get_1_2_perfect():
    x = sp.Symbol("x")
    # a0, b0, c0 = random.randint(-5, 6), random.randint(-5, 6), random.randint(-5, 6)
    # first_ev = a0 * x ** 2 + b0 * x + c0
    a0, b0 = random.randint(-2, 4), random.randint(-2, 4)
    a1, b1 = random.choice([-2, -1, 1, 2, 3]), random.randint(-2, 4)
    a2, b2, c2 = random.choice([-2, -1, 1, 2, 3]), random.randint(-2, 4), random.randint(-2, 4),
    a3, b3 = random.randint(-2, 4), random.choice([-2, -1, 1, 2, 3])

    zero_ev = a0 * x + b0
    first_ev = a1 * x + b1
    second_ev = a2 * x ** 2 + b2 * x + c2
    third_ev = a3 * x + b3

    itog =(1 + ((zero_ev * first_ev) * sp.sin(third_ev / (first_ev * second_ev * third_ev)))) ** (first_ev)

    # print(itog)
    # print("(", 1, "+", "(", sp.expand((zero_ev * first_ev)), ")", sp.sin(third_ev / sp.expand((first_ev * second_ev * third_ev))), ")", "^", "(", first_ev, ")")
    answer = sp.limit(itog, x, sp.oo)
    res = r"\lim_{n \to \infty} {{" + "( 1 + (" + sp.latex(sp.expand((zero_ev * first_ev))) + ")" + sp.latex(sp.sin(third_ev / sp.expand((first_ev * second_ev * third_ev)))) + ")} ^ {" + sp.latex(first_ev) + "}" + "}"
    # print(sp.limit(itog, x, sp.oo))
    return ("formula", res), ("text",answer)


if __name__ == "__main__":
    print(get_1_2_perfect())
