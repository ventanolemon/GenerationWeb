"""
Готовые задания на моделях: имя → {title, subject_id, partition_id, graph}.

Зачем этот файл существует. Пять моделей (`core/models`) написаны,
оттестированы и видны в палитре — и до появления этого каталога ни одна
не выдавалась ни одному студенту: разделы обслуживались старыми
код-генераторами, теми самыми, у которых ответ живёт текстом. Модель без
графа — инструмент, которым никто не пользуется.

Каждый граф здесь — не витрина возможностей языка (для этого есть
`exercises/graph_examples`), а **задание, которое можно выдать**: условие
показывает то, по чему решают, ответ типизирован и проверяется.

Разделы добавляются РЯДОМ со старыми, а не вместо них. Замена сменила бы
содержимое уже выданных домашних заданий и разошлась бы с накопленной
статистикой попыток; вывод старых генераторов — отдельное решение, и
принимать его попутно неправильно.

Идентификаторы разделов взяты из свободного диапазона 200+ (у код-только
разделов — до сотни, у английского — 1000+).
"""

from __future__ import annotations

# ---------- Линал: собственные значения ----------
#
# Задание, которого до модели собрать было нельзя: у случайной матрицы
# собственные значения иррациональные, а узел `matrix_eigenvalues` отдаёт
# готовое оформление вместо величин.
_EIGENVALUES = {
    "nodes": [
        {"id": "m", "type": "model_linal_eigen",
         "params": {"size": 3, "min": -3, "max": 4}},
        {"id": "block", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A"}},
        {"id": "task", "type": "task", "params": {
            "statement": "Найдите собственные значения матрицы A.",
            "slots": ["λ:expr:много:label=собственные значения"],
        }},
    ],
    "edges": [
        {"from": "m:matrix", "to": "block:in"},
        {"from": "block:out", "to": "task:blocks"},
        {"from": "m:eigenvalues", "to": "task:λ"},
    ],
    "meta": {"seed": 11},
}


# ---------- Линал: характеристический многочлен ----------
#
# Вторая разводка ТОЙ ЖЕ модели: одна модель — несколько заданий.
_CHAR_POLY = {
    "nodes": [
        {"id": "m", "type": "model_linal_eigen",
         "params": {"size": 3, "min": -3, "max": 4}},
        {"id": "block", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A"}},
        {"id": "task", "type": "task", "params": {
            "statement": ("Выпишите характеристический многочлен матрицы A "
                          "— раскрытый определитель det(A − λE)."),
            "slots": ["p:expr:vars=lamda:label=многочлен"],
        }},
    ],
    "edges": [
        {"from": "m:matrix", "to": "block:in"},
        {"from": "block:out", "to": "task:blocks"},
        {"from": "m:char_poly", "to": "task:p"},
    ],
    "meta": {"seed": 12},
}


# ---------- Линал: треугольник по двум прямым ----------
#
# То самое задание, условие которого годами не давало того, по чему
# считался ответ (§2.8). Здесь условие и ответ приходят из одной модели,
# поэтому разойтись им негде.
_TRIANGLE = {
    "nodes": [
        {"id": "m", "type": "model_linal_triangle", "params": {}},
        {"id": "p1", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_1"}},
        {"id": "p2", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_2"}},
        {"id": "l13", "type": "expr_block",
         "params": {"prefix": "A_1A_3", "relation": ":\\;"}},
        {"id": "l23", "type": "expr_block",
         "params": {"prefix": "A_2A_3", "relation": ":\\;"}},
        {"id": "blocks", "type": "block_list", "params": {"count": 4}},
        {"id": "task", "type": "task", "params": {
            "statement": ("Вершины A₁ и A₂ заданы координатами, стороны "
                          "A₁A₃ и A₂A₃ лежат на данных прямых (выражение "
                          "равно нулю на прямой). Найдите вершину A₃."),
            "slots": ["A3:matrix:label=координаты A₃"],
        }},
    ],
    "edges": [
        {"from": "m:a1", "to": "p1:in"}, {"from": "m:a2", "to": "p2:in"},
        {"from": "m:line_a1a3", "to": "l13:in"},
        {"from": "m:line_a2a3", "to": "l23:in"},
        {"from": "p1:out", "to": "blocks:in0"},
        {"from": "p2:out", "to": "blocks:in1"},
        {"from": "l13:out", "to": "blocks:in2"},
        {"from": "l23:out", "to": "blocks:in3"},
        {"from": "blocks:out", "to": "task:blocks"},
        {"from": "m:a3", "to": "task:A3"},
    ],
    "meta": {"seed": 13},
}


# ---------- Линал: уравнение медианы ----------
#
# Ответ-уравнение: принимается любая пропорциональная запись, потому что
# `6x + 4y - 10 = 0` и `3x + 2y - 5 = 0` — одна прямая.
_MEDIAN = {
    "nodes": [
        {"id": "m", "type": "model_linal_triangle", "params": {}},
        {"id": "p1", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_1"}},
        {"id": "p2", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_2"}},
        {"id": "p3", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_3"}},
        {"id": "blocks", "type": "block_list", "params": {"count": 3}},
        {"id": "task", "type": "task", "params": {
            "statement": ("Выпишите общее уравнение медианы треугольника "
                          "A₁A₂A₃, проведённой через вершину A₃."),
            "slots": ["мед:equation:vars=x,y:label=уравнение медианы"],
        }},
    ],
    "edges": [
        {"from": "m:a1", "to": "p1:in"}, {"from": "m:a2", "to": "p2:in"},
        {"from": "m:a3", "to": "p3:in"},
        {"from": "p1:out", "to": "blocks:in0"},
        {"from": "p2:out", "to": "blocks:in1"},
        {"from": "p3:out", "to": "blocks:in2"},
        {"from": "blocks:out", "to": "task:blocks"},
        {"from": "m:median_a3", "to": "task:мед"},
    ],
    "meta": {"seed": 14},
}


# ---------- Линал: плоскость грани пирамиды ----------
_PLANE = {
    "nodes": [
        {"id": "m", "type": "model_linal_pyramid", "params": {}},
        {"id": "p2", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_2"}},
        {"id": "p3", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_3"}},
        {"id": "p4", "type": "matrix_block",
         "params": {"env": "pmatrix", "prefix": "A_4"}},
        {"id": "blocks", "type": "block_list", "params": {"count": 3}},
        {"id": "task", "type": "task", "params": {
            "statement": ("Выпишите общее уравнение плоскости, проходящей "
                          "через точки A₂, A₃, A₄."),
            "slots": ["пл:equation:vars=x,y,z:label=уравнение плоскости"],
        }},
    ],
    "edges": [
        {"from": "m:a2", "to": "p2:in"}, {"from": "m:a3", "to": "p3:in"},
        {"from": "m:a4", "to": "p4:in"},
        {"from": "p2:out", "to": "blocks:in0"},
        {"from": "p3:out", "to": "blocks:in1"},
        {"from": "p4:out", "to": "blocks:in2"},
        {"from": "blocks:out", "to": "task:blocks"},
        {"from": "m:plane_a2a3a4", "to": "task:пл"},
    ],
    "meta": {"seed": 15},
}


# ---------- ОПВС: функция по схеме, ответ собирается на холсте ----------
_CIRCUIT_CANVAS = {
    "nodes": [
        {"id": "m", "type": "model_opvs_circuit", "params": {"inputs": 3}},
        {"id": "img", "type": "image_block",
         "params": {"caption": "Логическая схема (ГОСТ 2.743-91)"}},
        {"id": "task", "type": "task", "params": {
            "statement": "Соберите схему, реализующую ту же функцию.",
            "slots": ["ф:logic:label=функция"],
            "widget": "circuit_canvas",
        }},
    ],
    "edges": [
        {"from": "m:image", "to": "img:in"},
        {"from": "img:out", "to": "task:blocks"},
        {"from": "m:expr", "to": "task:ф"},
    ],
    "meta": {"seed": 16},
}


# ---------- ОПВС: сколько наборов обращают функцию в единицу ----------
#
# Обратная разводка той же модели: спрашивается не функция, а её свойство.
_CIRCUIT_ONES = {
    "nodes": [
        {"id": "m", "type": "model_opvs_circuit", "params": {"inputs": 3}},
        {"id": "img", "type": "image_block",
         "params": {"caption": "Логическая схема (ГОСТ 2.743-91)"}},
        {"id": "task", "type": "task", "params": {
            "statement": ("Постройте таблицу истинности функции, заданной "
                          "схемой. Сколько наборов обращают её в единицу?"),
            "slots": ["n:number:label=число наборов"],
        }},
    ],
    "edges": [
        {"from": "m:image", "to": "img:in"},
        {"from": "img:out", "to": "task:blocks"},
        {"from": "m:ones", "to": "task:n"},
    ],
    "meta": {"seed": 17},
}


# ---------- ОПВС: что напечатает программа ----------
_CCODE_OUTPUT = {
    "nodes": [
        {"id": "m", "type": "model_opvs_ccode",
         "params": {"mistakes": 5, "kind": "loop"}},
        {"id": "listing", "type": "code_block", "params": {"language": "c"}},
        {"id": "task", "type": "task", "params": {
            "statement": "Что напечатает эта программа?",
            "slots": ["вывод:output:label=вывод программы"],
        }},
    ],
    "edges": [
        {"from": "m:code", "to": "listing:text"},
        {"from": "listing:out", "to": "task:blocks"},
        {"from": "m:output", "to": "task:вывод"},
    ],
    "meta": {"seed": 18},
}


# ---------- ОПВС: в каких строках изменён код ----------
_CCODE_LINES = {
    "nodes": [
        {"id": "m", "type": "model_opvs_ccode", "params": {"mistakes": 5}},
        {"id": "listing", "type": "code_block", "params": {"language": "c"}},
        {"id": "task", "type": "task", "params": {
            "statement": ("В программу внесено 5 синтаксических ошибок — по "
                          "одной на строку. Укажите номера этих строк."),
            "slots": ["строки:number:много:label=номера строк"],
        }},
    ],
    "edges": [
        {"from": "m:broken", "to": "listing:text"},
        {"from": "listing:out", "to": "task:blocks"},
        {"from": "m:lines", "to": "task:строки"},
    ],
    "meta": {"seed": 19},
}


#: Каталог. `partition_id` — из свободного диапазона 200+; `subject_id`
#: совпадает с тем, под которым предмет заводит `bootstrap.sync_database`.
TASKS: dict[str, dict] = {
    "eigenvalues": {
        "title": "Собственные значения матрицы",
        "subject_id": 1, "partition_id": 201, "graph": _EIGENVALUES,
    },
    "char_poly": {
        "title": "Характеристический многочлен",
        "subject_id": 1, "partition_id": 202, "graph": _CHAR_POLY,
    },
    "triangle_vertex": {
        "title": "Треугольник: вершина по двум прямым",
        "subject_id": 1, "partition_id": 203, "graph": _TRIANGLE,
    },
    "triangle_median": {
        "title": "Треугольник: уравнение медианы",
        "subject_id": 1, "partition_id": 204, "graph": _MEDIAN,
    },
    "pyramid_plane": {
        "title": "Пирамида: уравнение плоскости грани",
        "subject_id": 1, "partition_id": 205, "graph": _PLANE,
    },
    "circuit_canvas": {
        "title": "Логическая схема: собрать по функции",
        "subject_id": 11, "partition_id": 211, "graph": _CIRCUIT_CANVAS,
    },
    "circuit_ones": {
        "title": "Логическая схема: таблица истинности",
        "subject_id": 11, "partition_id": 212, "graph": _CIRCUIT_ONES,
    },
    "ccode_output": {
        "title": "Программа на C: что напечатает",
        "subject_id": 11, "partition_id": 213, "graph": _CCODE_OUTPUT,
    },
    "ccode_lines": {
        "title": "Программа на C: где ошибки",
        "subject_id": 11, "partition_id": 214, "graph": _CCODE_LINES,
    },
}


def task_names() -> list[str]:
    return sorted(TASKS)


def task_graph(name: str) -> dict:
    return TASKS[name]["graph"]
