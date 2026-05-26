"""
Главный модуль генерации физических задач.

Публичный API:
  * generate_fisic_task(config_str_or_dict) -> (condition, solution)
        Старый интерфейс, оставлен для обратной совместимости с БД и адаптерами.
  * FisicTask                                — готовый dataclass с условием,
        решением и метаданными (для нового кода).
  * generate_task(config) -> FisicTask        — основной точка входа.

Структура config (JSON или dict):

  {
    "condition":     "Найдите силу при массе #m# и ускорении #a#",
    "result_letter": "F",
    "formula":       "m * a",                  // поддерживается ^, √, π
    "dimension":     "Н",
    "result": {                                 // опционально
        "kind": "natural",                      // natural | integer | real
        "min": 1,
        "max": 1000
    },
    "max_attempts": 100,                        // опционально
    "variables": {
        "m": {
            "min": 1,
            "max": 100,
            "kind": "natural",                  // natural | integer | real | auto
            "step": 1,                          // опционально
            "forbidden": [0],
            "decimals": 2,
            "dimension": "кг"
        },
        "a": {
            "min": "0.5",
            "max": "10^2",                      // формула в диапазоне разрешена
            "kind": "real",
            "decimals": 1,
            "dimension": "м/с^2"
        }
    }
  }
"""

from __future__ import annotations
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .constraints import ResultConstraint
from .expression import (
    FormulaError, evaluate_formula, parse_formula, extract_variable_names,
)
from .formatting import format_number
from .generation import VariableSpec, generate_value, parse_variable_spec


# ---------- Структуры данных ----------

@dataclass
class FisicTask:
    """Результат успешной генерации."""
    condition: str
    solution: str
    values: dict[str, float] = field(default_factory=dict)
    result: float = 0.0
    formula: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class TaskConfig:
    """Полностью разобранная конфигурация задачи."""
    condition_template: str
    result_letter: str
    formula: str
    dimension: str
    variables: dict[str, VariableSpec]
    result_constraint: ResultConstraint
    max_attempts: int = 100

    @classmethod
    def parse(cls, config: str | dict) -> "TaskConfig":
        if isinstance(config, str):
            config = json.loads(config)
        if not isinstance(config, dict):
            raise ValueError("Конфиг задачи должен быть dict или JSON-строкой.")

        try:
            condition = config["condition"]
            result_letter = config["result_letter"]
            formula = config["formula"]
            dimension = config.get("dimension", "")
        except KeyError as e:
            raise ValueError(f"В конфиге не хватает ключа: {e}")

        # Проверим формулу заранее — лучше упасть здесь, чем в цикле генерации
        parse_formula(formula)

        variables = {}
        for name, var_cfg in (config.get("variables") or {}).items():
            variables[name] = parse_variable_spec(name, var_cfg)

        # Сверим, что переменные из формулы покрыты конфигом
        used_in_formula = extract_variable_names(formula)
        missing = used_in_formula - set(variables.keys())
        if missing:
            raise ValueError(
                f"В формуле использованы переменные {sorted(missing)}, "
                "но они не описаны в конфиге."
            )

        result_constraint = ResultConstraint.parse(config.get("result"))
        max_attempts = int(config.get("max_attempts", 100))

        return cls(
            condition_template=condition,
            result_letter=result_letter,
            formula=formula,
            dimension=dimension,
            variables=variables,
            result_constraint=result_constraint,
            max_attempts=max_attempts,
        )


# ---------- Основной алгоритм ----------

def generate_task(config: str | dict | TaskConfig) -> FisicTask:
    """
    Сгенерировать задачу с заданными ограничениями.

    Алгоритм:
      1. Разобрать конфиг и формулу один раз (а не в каждой попытке).
      2. До max_attempts раз:
         a) сгенерировать значения переменных по их спецификациям;
         b) вычислить формулу;
         c) проверить результат на ResultConstraint;
         d) если ОК — собрать FisicTask и вернуть.
      3. Если все попытки провалились — RuntimeError с диагностикой.
    """
    cfg = config if isinstance(config, TaskConfig) else TaskConfig.parse(config)

    # Разбираем формулу один раз: это важно для производительности при
    # большом max_attempts (ResultConstraint может потребовать много попыток).
    parsed = parse_formula(cfg.formula)

    last_error: Exception | None = None

    for _ in range(cfg.max_attempts):
        try:
            values = {
                name: generate_value(spec)
                for name, spec in cfg.variables.items()
            }
        except RuntimeError as e:
            # Не получилось сгенерировать одну из переменных — нет смысла
            # продолжать, проблема в конфиге переменной.
            raise

        try:
            result = evaluate_formula(parsed, values)
        except (OverflowError, ValueError, ZeroDivisionError) as e:
            last_error = e
            continue

        if math.isinf(result) or math.isnan(result):
            continue

        if not cfg.result_constraint.check(result):
            continue

        result = cfg.result_constraint.normalize(result)
        return _build_task(cfg, values, result)

    raise RuntimeError(
        f"Не удалось сгенерировать задачу за {cfg.max_attempts} попыток. "
        f"Возможно, ограничение на результат (kind={cfg.result_constraint.kind}) "
        "слишком жёсткое для заданных диапазонов переменных. "
        + (f"Последняя ошибка вычисления: {last_error}" if last_error else "")
    )


def _build_task(
    cfg: TaskConfig, values: Mapping[str, float], result: float
) -> FisicTask:
    """Собрать готовую FisicTask из значений переменных и результата."""
    # Подставляем значения в шаблон условия
    condition = cfg.condition_template
    for name, value in values.items():
        spec = cfg.variables[name]
        # Натуральные/целые значения форматируем без научной нотации
        if spec.kind in ("natural", "integer"):
            formatted = format_number(
                value, scientific_threshold_high=float("inf")
            )
        else:
            formatted = format_number(value, decimals=spec.decimals)
        replacement = f"{formatted} {spec.dimension}".strip()
        condition = condition.replace(f"#{name}#", replacement)

    # Форматируем результат. Для натуральных/целых результатов отключаем
    # научную нотацию, иначе 87000 покажется как 8.7×10^4 — менее наглядно.
    if cfg.result_constraint.kind in ("natural", "integer"):
        formatted_result = format_number(
            result, scientific_threshold_high=float("inf")
        )
    else:
        formatted_result = format_number(result)

    solution = f"{cfg.result_letter} = {formatted_result}"
    if cfg.dimension:
        solution += f" {cfg.dimension}"

    return FisicTask(
        condition=condition,
        solution=solution,
        values=dict(values),
        result=result,
        formula=cfg.formula,
        meta={
            "result_kind": cfg.result_constraint.kind,
        },
    )


# ---------- Старый API для обратной совместимости ----------

def generate_fisic_task(task_config: str | dict) -> tuple[str, str]:
    """
    Старый интерфейс. Возвращает кортеж (условие, решение).
    Используется адаптером FisicConstructorGenerator и тестами.
    """
    task = generate_task(task_config)
    return task.condition, task.solution


# ---------- Пример конфигурации (для ручного запуска) ----------

EXAMPLE_CONFIG = '''
{
  "condition": "В книге #pages# страниц. На каждой странице #words# слов. Сколько всего слов в книге?",
  "result_letter": "N",
  "formula": "pages * words",
  "dimension": "слов",
  "result": {"kind": "natural", "min": 100},
  "variables": {
    "pages":  {"min": 50,  "max": 500,  "kind": "natural", "dimension": "стр"},
    "words":  {"min": 100, "max": 400,  "kind": "natural", "dimension": "сл/стр"}
  }
}
'''


if __name__ == "__main__":
    cond, sol = generate_fisic_task(EXAMPLE_CONFIG)
    print("Условие:", cond)
    print("Решение:", sol)
