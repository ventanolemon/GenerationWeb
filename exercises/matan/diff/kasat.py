import sympy as sp
import random

x = sp.Symbol('x')
GOOD_POINTS = [i for i in range(-9, 10)]
random.shuffle(GOOD_POINTS)


def safe_function():
    """Генерирует f(x) = P(x) * (Q(x))**(1/n) и точку x0,
    где Q(x0) = k**n, чтобы корень был целым/рациональным."""

    # Простые многочлены-кандидаты для P(x) и Q(x)
    a = random.randint(0, 9)
    polys = [
        x + 1 + a,
        x - 1 + a,
        x + 2 + a,
        x - 2 + a,
        2 - x + a,
        3 - x + a,
        x + 3 + a,
        2*x + 1 + a,
        x**2 + 1 + a,
        x**2 - 1 + a,
        1 - x**2 + a,
    ]

    # Возможные степени корней (n=1 означает "без корня", т.е. **1)
    roots_info = [
        (1, []),                     # n=1 → просто Q(x)
        (2, [0, 1, 4, 9]),          # n=2 → нужны Q = 0,1,4,9 (квадраты)
        (3, [-8, -1, 0, 1, 8]),     # n=3 → нужны Q = -8,-1,0,1,8 (кубы)
        (4, [0, 1, 16]),            # n=4 → нужны Q = 0,1,16 (4-е степени)
    ]

    for _ in range(30):
        P, Q = random.sample(polys, k=2)
        n, target_vals = random.choice(roots_info)

        # Подбираем x0 ∈ GOOD_POINTS такой, что Q(x0) ∈ target_vals
        candidates = []
        for x0 in GOOD_POINTS:
            try:
                q_val = sp.simplify(Q.subs(x, x0))
                if q_val not in target_vals:
                    continue

                # Для чётных n: подкоренное должно быть ≥ 0
                if n % 2 == 0 and q_val < 0:
                    continue

                # Вычисляем корень: (Q(x0))**(1/n)
                root_val = q_val ** sp.Rational(1, n) if n != 1 else q_val
                if not root_val.is_real:
                    continue

                f_val = sp.simplify(P.subs(x, x0) * root_val)
                if not (f_val.is_real and f_val.is_finite):
                    continue

                # Проверим, что производная тоже будет конечной
                # (для корней чётной степени в нуле может быть проблема: sqrt(x) в 0 — производная ∞)
                if n == 2 and q_val == 0:
                    # sqrt(Q(x)) в точке, где Q=0: производная = P(x0) * Q'(x0) / (2*sqrt(Q(x))) → ∞, если Q'(x0) ≠ 0
                    Qp = sp.diff(Q, x)
                    if Qp.subs(x, x0) != 0:
                        continue  # пропускаем особые точки
                if n == 4 and q_val == 0:
                    Qp = sp.diff(Q, x)
                    if Qp.subs(x, x0) != 0:
                        continue
                if x0 != 0:
                    candidates.append(x0)
            except Exception:
                continue

        if not candidates:
            continue

        x0 = random.choice(candidates)

        # Собираем функцию
        if n == 1:
            f = P * Q
        else:
            f = P * (Q ** sp.Rational(1, n))

        # Финальная проверка: f и f' конечны в x0
        try:
            f = sp.simplify(f)
            df = sp.diff(f, x)
            f0 = f.subs(x, x0)
            df0 = df.subs(x, x0)

            if any(val.has(sp.zoo, sp.nan) or not val.is_finite or not val.is_real
                   for val in [f0, df0]):
                continue

            # Дополнительно: избегаем сложных радикалов в ответе (например, sqrt(2))
            # Оставляем только случаи, где f0 и df0 — рациональные
            if not (f0.is_rational and df0.is_rational):
                # Попробуем оценить численно и проверить близость к рациональному
                f0_n = sp.nsimplify(sp.N(f0, 12), [sp.sqrt(2), sp.sqrt(3)], maxsteps=5)
                df0_n = sp.nsimplify(sp.N(df0, 12), [sp.sqrt(2), sp.sqrt(3)], maxsteps=5)
                if not (f0_n.is_rational and df0_n.is_rational):
                    continue

            return f, x0

        except Exception:
            continue

    # Fallback: простая, гарантированно хорошая функция
    return (x + 1) * sp.sqrt(x + 1), 0  # при x0=0: sqrt(1)=1, f=1, f'=1.5 — рационально


# --- Вспомогательные функции (без изменений) ---

def tangent_line(f, x0):
    """Возвращает уравнение касательной: y = f'(x0)*(x - x0) + f(x0)"""
    f0 = sp.simplify(f.subs(x, x0))
    df = sp.diff(f, x)
    df0 = sp.simplify(df.subs(x, x0))
    tangent = df0 * (x - x0) + f0
    return sp.simplify(tangent)


def get_tangent_line():
    f, x0 = safe_function()  # ← теперь возвращает и функцию, и точку
    tangent = tangent_line(f, x0)

    task = sp.Eq(sp.Symbol('y'), f)
    task_latex = sp.latex(task) + f" \\quad \\text{{в точке }} x_0 = {x0}"

    answer_eq = sp.Eq(sp.Symbol('y'), tangent)
    answer_latex = sp.latex(answer_eq)

    return (("text", " 6.\tНаписать уравнение касательной к графику функции\n"),
            ("formula", task_latex),
            ("formula", answer_latex))


# --- Тест ---
if __name__ == "__main__":
    for i in range(5):
        task, ans = get_tangent_line()
        print(f"\n--- Вариант {i+1} ---")
        print("Задание:", task[1])
        print("Ответ:   ", ans[1])
        print("__________________")
