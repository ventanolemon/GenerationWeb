import random
import sympy


def get_simple_stepens():
    x = sympy.Symbol("x")

    # для знаменателя
    stepen_zn_1, stepen_zn_2, stepen_zn_3 = random.randint(2, 7), random.randint(2, 7), random.choice(range(2, 8, 2))
    a1, b1 = random.choice([-2, -1, 1, 2]), random.randint(-2, 4)
    a2, b2 = random.choice([-2, -1, 1, 2]), random.randint(-2, 4)

    first_ev = (a1 * x ** stepen_zn_1 + b1) * x
    second_ev = sympy.sqrt((a2 * x ** stepen_zn_2 + b2)) ** stepen_zn_3
    znam = first_ev * second_ev

    # для числителя
    stepen_1, stepen_2, = random.randint(2, 7), random.randint(2, 7)
    a0, b0 = random.choice([1, 2, 3]), random.randint(2, 3)
    zero_ev = a0 * x + b0
    c = random.randint(2, 10)
    chisl = sympy.sqrt(c * x ** stepen_1) + sympy.sqrt(zero_ev) ** (stepen_zn_2 * stepen_zn_3 + 2 * stepen_zn_1 + 2)
    result = r"{\frac{" + sympy.latex(chisl) + "}{" + sympy.latex(znam) + "}}"
    res = r"\lim_{x \to \infty} " + result
    # print(stepen_zn_2, stepen_zn_3, zero_ev)
    return ("formula", res), ("text", str(sympy.limit(chisl / znam, x, sympy.oo)))
    #
    # result = r"{\frac{" + sympy.latex(sympy.expand(itog_1)) + "}{" + sympy.latex(sympy.expand(itog_2)) + "}}"
    # res = r"\lim_{x \to \infty} " + result
    # return ("formula", res), ("text", str(sympy.limit(itog_1 / itog_2, x, sympy.oo)))


if __name__ == "__main__":
    print(get_simple_stepens())
    # print("(", sympy.expand(itog_1), ")", "/", "(", sympy.expand(itog_2), ")")
    # print(sympy.limit(itog_1 / itog_2, x, sympy.oo))