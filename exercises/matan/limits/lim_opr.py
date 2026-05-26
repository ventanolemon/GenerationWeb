import random as rnd


def get_lim_opr():
    a_0 = rnd.randint(0, 100)
    a = rnd.choice([f"{a_0}{rnd.choice(('', '-0', '+0'))}", f"{rnd.choice(('', '-', '+'))}∞"])
    b_0 = rnd.randint(0, 100)
    b = rnd.choice([f"{b_0}", f"{rnd.choice(('', '-', '+'))}∞"])
    # print(f"limit (x->{a}) (f(x)) = {b}")
    task = f"limit (x->{a}) (f(x)) = {b}"
    task = r"\lim_{x \to " + a + r"} {f(x)} = " + b
    # print('\N{GREEK SMALL LETTER EPSILON} \N{GREEK SMALL LETTER DELTA}')
    # print("ε", "∀", "δ")

    # res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: => f(x)"
    if b == "∞":
        if "∞" in a:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x < -δ => |f(x)| > ε"
            elif "+" in a:
                res =f"∀ε>0 ∃ δ(ε) > 0 ∀x: x > δ => |f(x)| > ε"
            else:
                res =f"∀ε>0 ∃ δ(ε) > 0 ∀x: |x| > δ => |f(x)| > ε"

        else:
            if "-" in a:
                res =f"∀ε>0 ∃ δ(ε) > 0 ∀x: -δ < x - {a_0} < 0 => |f(x)| > ε"

            elif "+" in a:
                res =f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < x - {a_0} < δ => |f(x)| > ε"

            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < |x - {a_0}| < δ => |f(x)| > ε"

    elif b == "+∞":
        if "∞" in a:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x < -δ => |f(x)| > ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x > δ => |f(x)| > ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: |x| > δ => |f(x)| > ε"
        else:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: -δ < x - {a_0} < 0 => f(x) > ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < x - {a_0} < δ => f(x) > ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < |x - {a_0}| < δ => f(x) > ε"
    elif b == "-∞":
        if "∞" in a:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x < -δ => f(x) < -ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x > δ => f(x) < -ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: |x| > δ => f(x) < -ε"
        else:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: -δ < x - {a_0} < 0 => f(x) < -ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < x - {a_0} < δ => f(x) < -ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < |x - {a_0}| < δ => f(x) < -ε"
    else:
        if "∞" in a:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x < -δ => |f(x) - {b_0}| < ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: x > δ => |f(x) - {b_0}| < ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: |x| > δ => |f(x) - {b_0}| < ε"
        else:
            if "-" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: -δ < x - {a_0} < 0 => |f(x) - {b_0}| < ε"
            elif "+" in a:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < x - {a_0} < δ => |f(x) - {b_0}| < ε"
            else:
                res = f"∀ε>0 ∃ δ(ε) > 0 ∀x: 0 < |x - {a_0}| < δ => |f(x) - {b_0}| < ε"
    return ("formula", task), ("text", res)
