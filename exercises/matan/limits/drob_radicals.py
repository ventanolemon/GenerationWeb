import random

import sympy


def get_drob_radicals():
    x = sympy.Symbol("x")
    a = random.randint(4, 9)
    varints_sq_1 = [i ** 2 for i in range(1, int(a ** 0.5))]
    varints_sq_2 = [i ** 2 for i in range(int(a ** 0.5), 9)]
    sq_1, sq_2 = random.choice(varints_sq_1), random.choice(varints_sq_2)

    zero_ev = x ** 2 - a ** 2

    b, c = a - sq_1, sq_2 - a
    first_ev = sympy.sqrt(x - b)
    second_ev = sympy.sqrt(x + c)
    # print(a, sq_1, sq_2)
    if random.randint(0, 2):
        third_ev = second_ev - sympy.sqrt(sq_2 / sq_1) * first_ev
        chisl_latex = sympy.latex(second_ev) + " - " + sympy.latex(sympy.sqrt(sq_2 / sq_1) * first_ev)
    else:
        third_ev =  sympy.sqrt(sq_2 / sq_1) * first_ev - second_ev
        chisl_latex = sympy.latex(sympy.sqrt(sq_2 / sq_1) * first_ev) + " - " + sympy.latex(second_ev)

    result = third_ev / zero_ev

    # res = r"\lim_{x \to " + str(a) + "} {" + sympy.latex(result) + "}"
    res =  r"\lim_{x \to " + str(a) + "} " + "{\\frac{" + chisl_latex + "}{" + sympy.latex(zero_ev) + "}}"
    return ("formula", res.replace(".0", "")), ("text", str(sympy.limit(result, x, a)))


if __name__ == "__main__":
    print(get_drob_radicals())
