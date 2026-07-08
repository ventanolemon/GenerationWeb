"""
Каталог граф-примеров: имя → {title, note, graph}.

Каждый graph — самостоятельный GraphSpec (nodes/edges/meta), который движок
GraphExecutor собирает и исполняет в StaticTask. Примеры подобраны так, чтобы
покрыть разные возможности языка и служить и витриной, и регрессионным набором.

meta.seed зафиксирован для воспроизводимости (тест может его переопределить).
"""

from __future__ import annotations


# ---------- 1. Числовое задание с проверкой результата ----------
_PHYSICS_FORCE = {
    "nodes": [
        {"id": "m", "type": "random_natural", "params": {"min": 1, "max": 20}},
        {"id": "a", "type": "random_natural", "params": {"min": 1, "max": 9}},
        {"id": "f", "type": "formula", "params": {"expr": "m * a"}},
        {"id": "chk", "type": "constraint",
         "params": {"kind": "natural", "min": 10, "max": 150}},
        {"id": "cond", "type": "text",
         "params": {"text": "Масса #m# кг, ускорение #a# м/с². Найдите силу."}},
        {"id": "ans", "type": "text", "params": {"text": "F = #F# Н"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "m:out", "to": "f:m"}, {"from": "a:out", "to": "f:a"},
        {"from": "f:out", "to": "chk:in"},
        {"from": "m:out", "to": "cond:m"}, {"from": "a:out", "to": "cond:a"},
        {"from": "chk:out", "to": "ans:F"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 3, "max_attempts": 100},
}


# ---------- 2. Пул вариантов: случайный выбор функции в условие ----------
_CHOICE_POOL_LIMIT = {
    "nodes": [
        {"id": "f", "type": "random_choice",
         "params": {"elem_type": "string",
                    "items": ["sin(x)", "tan(x)", "arcsin(x)", "ln(1+x)"]}},
        {"id": "cond", "type": "text",
         "params": {"text": "Найдите предел #f# / x при x → 0."}},
        {"id": "ans", "type": "text", "params": {"text": "Предел равен 1."}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "f:out", "to": "cond:f"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 7},
}


# ---------- 3. Полиморфный текст: выбор ВЫРАЖЕНИЯ → проза + производная ----------
_CHOICE_EXPR_DIFF = {
    "nodes": [
        {"id": "f", "type": "random_choice",
         "params": {"elem_type": "expr",
                    "items": ["sin(x)", "x**3", "exp(x)", "cos(2*x)"]}},
        {"id": "d", "type": "diff"},
        {"id": "cond", "type": "text",
         "params": {"text": "Найдите производную функции y = #f#."}},
        {"id": "ans", "type": "expr_block", "params": {"prefix": "y'"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "f:out", "to": "d:in"},
        {"from": "f:out", "to": "cond:f"},
        {"from": "d:out", "to": "ans:in"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 2},
}


# ---------- 4. Производная многочлена (авто-переменная, без узла symbol) ----------
_DERIVATIVE = {
    "nodes": [
        {"id": "p", "type": "random_polynomial",
         "params": {"var": "x", "degree": 3}},
        {"id": "d", "type": "diff"},
        {"id": "cond", "type": "expr_block", "params": {"prefix": "y"}},
        {"id": "ans", "type": "expr_block", "params": {"prefix": "y'"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "p:out", "to": "d:in"},
        {"from": "p:out", "to": "cond:in"},
        {"from": "d:out", "to": "ans:in"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 2},
}


# ---------- 5. Предел рациональной функции (авто-переменная) ----------
_LIMIT = {
    "nodes": [
        {"id": "e", "type": "expr_const",
         "params": {"expr": "(x**2 - 9)/(x - 3)"}},
        {"id": "ld", "type": "limit_display", "params": {"point": "3"}},
        {"id": "lim", "type": "limit", "params": {"point": "3"}},
        {"id": "cond", "type": "expr_block",
         "params": {"prefix": "Вычислите:", "relation": ""}},
        {"id": "ans", "type": "expr_block", "params": {"prefix": "="}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "e:out", "to": "ld:in"}, {"from": "e:out", "to": "lim:in"},
        {"from": "ld:out", "to": "cond:in"}, {"from": "lim:out", "to": "ans:in"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 1},
}


# ---------- 6. Определитель случайной матрицы 3×3 ----------
_DETERMINANT = {
    "nodes": [
        {"id": "A", "type": "random_matrix",
         "params": {"rows": 3, "cols": 3, "min": -3, "max": 3}},
        {"id": "det", "type": "matrix_det"},
        {"id": "t", "type": "text",
         "params": {"text": "Вычислите определитель матрицы:"}},
        {"id": "mb", "type": "matrix_block", "params": {"prefix": "A"}},
        {"id": "bl", "type": "block_list", "params": {"count": 2}},
        {"id": "ans", "type": "expr_block", "params": {"prefix": "det A"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "A:out", "to": "det:in"}, {"from": "A:out", "to": "mb:in"},
        {"from": "t:out", "to": "bl:in0"}, {"from": "mb:out", "to": "bl:in1"},
        {"from": "det:out", "to": "ans:in"},
        {"from": "bl:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 5},
}


# ---------- 7. Квадратное уравнение с целыми корнями (solve) ----------
# Уравнение собирается одним блоком: Eq(expand((x-a)(x-b)), 0) → 'x²−5x+6 = 0'.
_QUADRATIC = {
    "nodes": [
        {"id": "r1", "type": "random_natural", "params": {"min": 1, "max": 6}},
        {"id": "r2", "type": "random_natural", "params": {"min": 1, "max": 6}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["a", "b"]}},
        {"id": "eq", "type": "expr_const",
         "params": {"expr": "Eq(expand((x - a)*(x - b)), 0)",
                    "vars": ["a", "b"]}},
        {"id": "cond", "type": "expr_block",
         "params": {"prefix": "Решите уравнение:", "relation": ""}},
        {"id": "ans", "type": "solve", "params": {"prefix": "x"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "r1:out", "to": "vd:a"}, {"from": "r2:out", "to": "vd:b"},
        {"from": "vd:out", "to": "eq:values"},
        {"from": "eq:out", "to": "cond:in"},
        {"from": "eq:out", "to": "ans:in"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 4},
}


# ---------- 8. Отбраковка по условию: x — полный квадрат (guard) ----------
_GUARD_SQUARE = {
    "nodes": [
        {"id": "x", "type": "random_natural", "params": {"min": 2, "max": 80}},
        {"id": "r", "type": "formula", "params": {"expr": "sqrt(x)"}},
        {"id": "chk", "type": "number_check", "params": {"check": "integer"}},
        {"id": "g", "type": "guard", "params": {"mode": "require_true"}},
        {"id": "cond", "type": "text",
         "params": {"text": "Извлеките корень: √#x#."}},
        {"id": "ans", "type": "to_block", "params": {"prefix": "√x"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "x:out", "to": "r:x"}, {"from": "r:out", "to": "chk:in"},
        {"from": "chk:out", "to": "g:cond"}, {"from": "r:out", "to": "g:value"},
        {"from": "x:out", "to": "cond:x"}, {"from": "g:out", "to": "ans:in"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 3, "max_attempts": 300},
}


# ---------- 9. Генерация в цикле: таблица квадратов (repeat + to_block) ----------
_TABLE_SQUARES = {
    "nodes": [
        {"id": "rep", "type": "repeat", "params": {"count": 5, "body": {
            "nodes": [
                {"id": "i", "type": "loop_index"},
                {"id": "n", "type": "formula", "params": {"expr": "i + 1"}},
                {"id": "s", "type": "formula", "params": {"expr": "n * n"}},
                {"id": "row", "type": "text", "params": {"text": "#n#² = #s#"}},
            ],
            "edges": [
                {"from": "i:out", "to": "n:i"},
                {"from": "n:out", "to": "s:n"},
                {"from": "n:out", "to": "row:n"},
                {"from": "s:out", "to": "row:s"},
            ],
        }}},
        {"id": "ans", "type": "text", "params": {"text": "Таблица квадратов 1–5."}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "rep:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 1},
}


# ---------- 10. Матрица из цикла: туннель → list_to_matrix ----------
_MATRIX_IN_LOOP = {
    "nodes": [
        {"id": "rep", "type": "repeat", "params": {
            "count": 6, "outputs": ["xs:number:list"], "body": {
                "nodes": [
                    {"id": "v", "type": "random_natural",
                     "params": {"min": 1, "max": 9}},
                    {"id": "ov", "type": "output_var",
                     "params": {"name": "xs", "type": "number"}},
                ],
                "edges": [{"from": "v:out", "to": "ov:value"}],
            }}},
        {"id": "m", "type": "list_to_matrix", "params": {"rows": 2}},
        {"id": "t", "type": "text", "params": {"text": "Найдите ранг матрицы:"}},
        {"id": "mb", "type": "matrix_block", "params": {"prefix": "A"}},
        {"id": "bl", "type": "block_list", "params": {"count": 2}},
        {"id": "rk", "type": "matrix_rank"},
        {"id": "ans", "type": "to_block", "params": {"prefix": "rang A"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "rep:xs", "to": "m:items"},
        {"from": "m:out", "to": "mb:in"}, {"from": "m:out", "to": "rk:in"},
        {"from": "t:out", "to": "bl:in0"}, {"from": "mb:out", "to": "bl:in1"},
        {"from": "rk:out", "to": "ans:in"},
        {"from": "bl:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 5},
}


# ---------- 11. Выбор ветви: case по случайному селектору ----------
_CASE_VARIANT = {
    "nodes": [
        {"id": "sel", "type": "random_natural", "params": {"min": 0, "max": 2}},
        {"id": "cs", "type": "case", "params": {"cases": 3,
            "case_0": {"nodes": [{"id": "t", "type": "text",
                "params": {"text": "Тип A: предел при x→0."}}], "edges": []},
            "case_1": {"nodes": [{"id": "t", "type": "text",
                "params": {"text": "Тип B: предел при x→∞."}}], "edges": []},
            "case_2": {"nodes": [{"id": "t", "type": "text",
                "params": {"text": "Тип C: односторонний предел."}}], "edges": []},
        }},
        {"id": "ans", "type": "text", "params": {"text": "См. методичку."}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "sel:out", "to": "cs:selector"},
        {"from": "cs:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 4},
}


EXAMPLES: dict[str, dict] = {
    "physics_force": {
        "title": "Физика: сила F = m·a (с проверкой результата)",
        "note": "Случайные числа + формула + constraint (диапазон ответа) + текст.",
        "graph": _PHYSICS_FORCE,
    },
    "choice_pool_limit": {
        "title": "Предел: случайная функция из пула",
        "note": "random_choice (строка) → подстановка в текст условия.",
        "graph": _CHOICE_POOL_LIMIT,
    },
    "choice_expr_diff": {
        "title": "Производная случайной функции из пула",
        "note": "random_choice (выражение) питает и прозу, и символьный конвейер.",
        "graph": _CHOICE_EXPR_DIFF,
    },
    "derivative_poly": {
        "title": "Производная многочлена",
        "note": "random_polynomial → diff с авто-переменной (без узла symbol).",
        "graph": _DERIVATIVE,
    },
    "limit_rational": {
        "title": "Предел рациональной функции",
        "note": "expr_const → limit/limit_display, переменная выводится авто.",
        "graph": _LIMIT,
    },
    "determinant_3x3": {
        "title": "Определитель матрицы 3×3",
        "note": "random_matrix → matrix_det; матрица и ответ как блоки.",
        "graph": _DETERMINANT,
    },
    "quadratic_solve": {
        "title": "Квадратное уравнение с целыми корнями",
        "note": "(x−a)(x−b) → expand → solve; условие и корни.",
        "graph": _QUADRATIC,
    },
    "guard_perfect_square": {
        "title": "Корень из полного квадрата (отбраковка)",
        "note": "guard: число пере-генерируется, пока √x не целое.",
        "graph": _GUARD_SQUARE,
    },
    "table_squares": {
        "title": "Таблица квадратов через цикл",
        "note": "repeat: тело строит строку на каждой итерации → список блоков.",
        "graph": _TABLE_SQUARES,
    },
    "matrix_in_loop": {
        "title": "Матрица из значений, накопленных в цикле",
        "note": "repeat-туннель (список) → list_to_matrix → ранг.",
        "graph": _MATRIX_IN_LOOP,
    },
    "case_variant": {
        "title": "Случайный вариант задания (выбор ветви)",
        "note": "case по случайному селектору исполняет одну из ветвей.",
        "graph": _CASE_VARIANT,
    },
}


def example_names() -> list[str]:
    """Имена всех примеров (стабильный порядок)."""
    return list(EXAMPLES)


def example_graph(name: str) -> dict:
    """GraphSpec-словарь примера по имени."""
    return EXAMPLES[name]["graph"]
