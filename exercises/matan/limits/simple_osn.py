import random
from sympy import limit, Symbol, oo, latex, sqrt


def get_simple_osn(mode="easy"):
    n = Symbol("n")

    a, b, c, d = random.randint(2, 10), random.randint(2, 10), random.randint(2, 10), random.randint(2, 10)
    k1, k2, k3 = random.choice([-2, -1, 1, 2, 3]), random.choice([-2, -1, 1, 2, 3]), random.choice([-2, -1, 1, 2, 3])
    minus = [True, False, False]
    random.shuffle(minus)
    # part_1, part_2 = f"({a} ** (n + {k1}) + {b} ** n)", f"({a} ** (n + {k2}) + {b} ** (n + {k3}))"
    part_1, part_2 = a ** (n + k1) + b ** (-n if minus[0] else n), a ** (sqrt(n + k3) if minus[1] else n + k2) + b ** (sqrt(n + k3) if minus[2] else n + k3)
    # if "n + -" in part_1:
    #     part_1 = part_1.replace("n + -", "n - ")
    # elif "n + -" in part_2:
    #     part_2 = part_2.replace("n + -", "n - ")
    if random.randint(0, 2):
        result = part_1 / part_2
    else:
        result = part_1 / part_2

    # print(result)
    res = r"\lim_{n \to \infty} {" + latex(result) + "}"
    return ("formula", res), ("text", str(limit(result, n, oo)))


if __name__ == "__main__":
    print(get_simple_osn())
