import random
import sympy


def get_long_radicals():
    x = sympy.Symbol("x")
    # a0, b0, c0 = random.randint(-5, 6), random.randint(-5, 6), random.randint(-5, 6)
    # first_ev = a0 * x ** 2 + b0 * x + c0
    a0, b0 = random.randint(1,6), random.randint(1,6)
    a1, b1 = random.randint(1,6), random.randint(1,6)
    a2, b2 = a0, random.randint(-2, 4)
    a3, b3 = a1, random.randint(-2, 4)

    zero_ev = a0 * x + b0
    first_ev = a1 * x + b1
    second_ev = a2 * x + b2
    third_ev = a3 * x + b3
    # print(zero_ev, first_ev, second_ev, third_ev, sep=".....")
    itog = sympy.sqrt((zero_ev * first_ev).expand()) - sympy.sqrt((second_ev * third_ev).expand())
    res = r"\lim_{x \to \infty} {" + sympy.latex(sympy.sqrt((zero_ev * first_ev).expand())) + "-" + sympy.latex(sympy.sqrt((second_ev * third_ev).expand())) + "}"
    return ("formula", res),  ("formula", sympy.latex(sympy.limit(itog, x, sympy.oo)))


if __name__ == "__main__":
    print(get_long_radicals())
