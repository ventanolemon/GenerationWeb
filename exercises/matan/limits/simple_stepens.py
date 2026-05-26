import random
import sympy


def get_simple_stepens():
    x = sympy.Symbol("x")
    # a0, b0, c0 = random.randint(-5, 6), random.randint(-5, 6), random.randint(-5, 6)
    # first_ev = a0 * x ** 2 + b0 * x + c0
    a0, a2 = random.sample([-2, -1, 1, 2, 3], k=2)
    b0 = random.choice([-2, -1, 1, 2, 3, 4])
    a1, b1 = random.choice([-2, -1, 1, 2, 3]), random.randint(-2, 4)
    b2 = random.choice([-2, -1, 1, 2, 3, 4])
    a3, b3 = random.choice([-2, -1, 1, 2, 3]), random.randint(-2, 4)

    zero_ev = a0 * x + b0
    first_ev = a1 * x + b1
    second_ev = a2 * x + b2
    third_ev = a3 * x + b3

    # раскоментить, если допускаются бесконечности в ответе
    # k = random.choice([0] * 3 + [1, 2])
    # if k == 0:
    #     n = random.randint(2, 5)
    #     itog_1, itog_2 = (zero_ev ** n * first_ev), (first_ev ** n * second_ev)
    # elif k == 1:
    #     n = random.randint(2, 5)
    #     itog_1, itog_2  = (zero_ev ** n * first_ev * third_ev), (first_ev * second_ev)
    # elif k == 2:
    #     n = random.randint(2, 5)
    #     itog_1, itog_2  = (zero_ev * first_ev ** n), (first_ev ** n * second_ev * third_ev)
    n = random.randint(2, 5)
    itog_1, itog_2 = (zero_ev ** n * first_ev), (first_ev ** n * second_ev)
    result = r"{\frac{" + sympy.latex(sympy.expand(itog_1)) + "}{" + sympy.latex(sympy.expand(itog_2)) + "}}"
    res = r"\lim_{x \to \infty} " + result
    return ("formula", res), ("text", str(sympy.limit(itog_1 / itog_2, x, sympy.oo)))


if __name__ == "__main__":
    print(get_simple_stepens()[0].replace(r"\\", '\\'))
    # print("(", sympy.expand(itog_1), ")", "/", "(", sympy.expand(itog_2), ")")
    # print(sympy.limit(itog_1 / itog_2, x, sympy.oo))