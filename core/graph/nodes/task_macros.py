"""
Узлы-макросы (категория task) — готовые задания в одном узле.

Для типовых заданий незачем собирать конвейер из источников, формул и блоков —
макро-узел берёт это на себя. Самый частый случай — числовое задание:
объявить переменные с диапазонами, написать шаблон условия и формулу ответа,
получить сразу TASK.

Эти узлы НЕ заменяют низкоуровневые (formula/text/static_task) — те остаются
для гибких и продвинутых сценариев. Макро-узел — быстрый старт для новичка.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


def _parse_var_ranges(specs):
    """
    Разобрать список 'имя:min:max[:kind]' в [(имя, lo, hi, kind)].
    kind: natural (по умолчанию) / integer / real. Диапазон обязателен.
    """
    out = []
    seen = set()
    for raw in (specs or []):
        s = str(raw).strip()
        if not s:
            continue
        parts = [p.strip() for p in s.split(":")]
        if len(parts) < 3:
            raise GraphValidationError(
                f"Переменная {s!r}: нужен формат 'имя:min:max[:тип]'."
            )
        name, lo, hi = parts[0], parts[1], parts[2]
        kind = parts[3] if len(parts) > 3 and parts[3] else "natural"
        if not name or name in seen:
            raise GraphValidationError(f"Переменная {name!r}: пустое/дублирующееся имя.")
        seen.add(name)
        try:
            lo_v, hi_v = float(lo), float(hi)
        except ValueError:
            raise GraphValidationError(f"Переменная {name!r}: min/max не числа.")
        if kind not in ("natural", "integer", "real"):
            raise GraphValidationError(f"Переменная {name!r}: тип {kind!r} неизвестен.")
        out.append((name, lo_v, hi_v, kind))
    return out


class SimpleTaskNode(Node):
    """
    Числовое задание в одном узле: переменные с диапазонами → подстановка в
    шаблоны условия и ответа. Сразу выдаёт TASK — без отдельных источников,
    формул и блоков.

    Параметры:
      variables — список 'имя:min:max[:тип]' (тип natural/integer/real);
      statement — текст условия с #имя# (и #ответ#, если включить в формулу);
      answer    — текст ответа с #имя#; поддерживает #=выражение# для вычислений;
      answer_formula — необязательная формула; её результат доступен как #result#.
    Случайные значения берутся из ctx.rng (воспроизводимо по seed).
    """
    type_id = "simple_task"
    category = "task"
    display_name = "Числовое задание"
    description = ("Числовое задание целиком: переменные с диапазонами + шаблоны "
                   "условия и ответа. Выход: TASK (без сборки конвейера).")
    OUTPUTS = [Port("out", PortType.TASK)]
    PARAMS_SCHEMA = {
        "variables": {"type": "list", "default": ["a:1:10", "b:1:10"]},
        "statement": {"type": "text", "default": "Сколько будет #a# + #b#?"},
        "answer_formula": {"type": "string", "default": "a + b", "optional": True},
        "answer": {"type": "text", "default": "#a# + #b# = #result#"},
    }

    def validate_params(self) -> None:
        _parse_var_ranges(self.params.get("variables"))

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock
        from exercises.fisic.generation import generate_value, parse_variable_spec
        from exercises.fisic.expression import evaluate_formula
        from .compute import _fill_template
        import math

        rng = ctx.rng
        values: dict[str, float] = {}
        for name, lo, hi, kind in _parse_var_ranges(self.params.get("variables")):
            spec = parse_variable_spec(name, {"min": lo, "max": hi, "kind": kind})
            values[name] = generate_value(spec)

        # Ответ-формула (если задана) доступна как #result#.
        formula = str(self.params.get("answer_formula", "")).strip()
        if formula:
            try:
                result = evaluate_formula(formula, values)
            except (OverflowError, ValueError, ZeroDivisionError) as e:
                raise RetryGeneration(f"simple_task {self.node_id!r}: {e}")
            if math.isinf(result) or math.isnan(result):
                raise RetryGeneration(f"simple_task {self.node_id!r}: результат inf/nan.")
            values["result"] = result

        fake_inputs = {"vars": values}
        statement = _fill_template(self.params.get("statement", ""), fake_inputs)
        answer = _fill_template(self.params.get("answer", ""), fake_inputs)

        from core.task import StaticTask
        return {"out": StaticTask(
            statement=[TextBlock(statement)],
            answer=[TextBlock(answer)],
            meta={"source": "graph"},
        )}
