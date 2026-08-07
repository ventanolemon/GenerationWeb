"""
Модули языка — организационная группировка категорий узлов (Этап 1, «дёшево»):
основа языка (core) + предметные модули (символьная математика, линал, ОДУ,
английский, изображения, графика).

Важно: это ТОЛЬКО группировка для палитры/документации. Движок как регистрировал
все узлы разом (`DEFAULT_REGISTRY`), так и продолжает — ни один узел никуда не
делся, граф с любым узлом исполняется независимо от того, скрыт ли его модуль
в палитре. «Настоящее» разделение (реестр собирается только из выбранных
модулей, а сохранённый граф декларирует зависимость от модуля в meta) — второй,
более трудоёмкий этап; см. обсуждение в docs/graph_addon.md.

MODULES: имя модуля → {title, description, categories, core}. category_module()
даёт обратную связь категория → модуль (для палитры и легенды типов).
"""

from __future__ import annotations


MODULE_ORDER = ["core", "symbolic", "linalg", "ode", "english",
                "informatics", "image", "plot"]

MODULES: dict[str, dict] = {
    "core": {
        "title": "Основа языка",
        "description": ("Общие узлы, нужные почти в любом графе: источники "
                        "чисел/строк, вычисление, управление потоком, списки, "
                        "блоки контента, сборка задания. Всегда включена."),
        "categories": ["task", "source", "compute", "control", "list",
                      "content", "assembly"],
        "core": True,
    },
    "symbolic": {
        "title": "Символьная математика",
        "description": "Алгебра, матан, ряды, ТФКП — sympy-выражения (EXPR).",
        "categories": ["symbolic"],
        "core": False,
    },
    "linalg": {
        "title": "Линейная алгебра",
        "description": "Матрицы и векторы (MATRIX): операции, системы, геометрия.",
        "categories": ["linalg"],
        "core": False,
    },
    "ode": {
        "title": "Дифференциальные уравнения",
        "description": "Решение и классификация ОДУ.",
        "categories": ["ode"],
        "core": False,
    },
    "english": {
        "title": "Английский язык",
        "description": "Словари слов, тренажёр, предложения с пропусками.",
        "categories": ["english"],
        "core": False,
    },
    "informatics": {
        "title": "Информатика",
        "description": ("Системы счисления и прочее, что нужно заданиям по "
                        "информатике. Своих типов портов не заводит — всё "
                        "едет числами, строками и списками."),
        "categories": ["informatics"],
        "core": False,
    },
    "image": {
        "title": "Изображения / ОПВС",
        "description": "Логические схемы, картинки из файла.",
        "categories": ["image"],
        "core": False,
    },
    "plot": {
        "title": "Графика на комплексной плоскости",
        "description": "Точки, области и конформные отображения ТФКП → картинка.",
        "categories": ["plot"],
        "core": False,
    },
}


def category_module(category: str) -> str:
    """Модуль, к которому отнесена категория узла; неизвестная → 'core'."""
    for name, mod in MODULES.items():
        if category in mod["categories"]:
            return name
    return "core"


def all_categories() -> set[str]:
    """Все категории, распределённые по модулям (для проверки полноты)."""
    return {cat for mod in MODULES.values() for cat in mod["categories"]}
