"""
GraphCompiler — компиляция графа задания в самостоятельный Python-модуль.

Идея: граф уже исполняется как dataflow (узлы в топопорядке, у каждого
compute(inputs, ctx)->outputs). Компилятор разворачивает этот же порядок в
читаемый прямолинейный код функции generate(seed) с явным retry-циклом.

Стратегия (гибрид «dataflow + инлайн простых»):
  * Частые простые узлы (константы, var_dict, formula, template, случайные
    числа, текстовый блок, список блоков, static_task) эмитятся как нативный
    Python — код читается как обычная генерация.
  * Все прочие ~85 узлов идут через универсальный путь: тот же класс узла
    инстанцируется из реестра и вызывается .compute(). Это гарантирует точное
    совпадение семантики без отдельного эмиттера под каждый узел.

Каждый выход узла получает переменную `_<node_id>_<port>` (id санитизируется в
идентификатор). Потребители ссылаются на эти переменные — провода становятся
обычными присваиваниями.

Сгенерированный модуль зависит только от пакета core.graph (реестр + рантайм-
хелперы), поэтому запускается там же, где установлен проект.
"""

from __future__ import annotations

import json
import keyword
import re

from .executor import GraphExecutor
from .spec import GraphSpec


# Узлы, для которых есть инлайн-эмиттер (нативный Python вместо .compute()).
# Остальные идут через универсальный путь _node(...).compute(...).
def _ident(node_id: str) -> str:
    """Превратить id узла в безопасный идентификатор Python."""
    s = re.sub(r"\W", "_", str(node_id))
    if not s or s[0].isdigit():
        s = "n_" + s
    if keyword.iskeyword(s):
        s = s + "_"
    return s


def _pylit(value) -> str:
    """Безопасный Python-литерал параметра (через repr/json)."""
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)) or value is None:
        return repr(value)
    # списки/словари/вложенные графы — через json-совместимый repr
    return repr(value)


class GraphCompiler:
    """Преобразует GraphSpec в исходный текст Python-модуля."""

    def __init__(self, spec: GraphSpec, registry=None,
                 func_name: str = "generate"):
        self.spec = spec
        self.func_name = func_name
        # Сборка через исполнитель: даёт валидацию, топопорядок, карту входов
        # и финальный TASK-узел — ровно то, что нужно для эмиссии.
        self.ex = GraphExecutor(spec, registry=registry)

    # ---------- Ссылки на выходы ----------

    def _out_var(self, node_id: str, port: str) -> str:
        return f"_{_ident(node_id)}_{port}"

    def _input_expr(self, node_id: str, port_name: str) -> str | None:
        """Python-выражение для значения, приходящего на вход (или None)."""
        src = self.ex.in_edges.get((node_id, port_name))
        if src is None:
            return None
        from_node, from_port = src
        return self._out_var(from_node, from_port)

    # ---------- Эмиссия ----------

    def compile(self) -> str:
        body: list[str] = []
        for node_id in self.ex.order:
            node = self.ex.nodes[node_id]
            body.extend(self._emit_node(node_id, node))

        # Возврат: значение финального TASK-узла, если он есть.
        if self.ex.result is not None:
            rnode, rport = self.ex.result
            ret = self._out_var(rnode, rport)
        else:
            ret = "None"

        meta = dict(self.spec.meta)
        try:
            max_attempts = int(meta.get("max_attempts", 100))
        except (TypeError, ValueError):
            max_attempts = 100
        seed_default = meta.get("seed")
        seed_lit = _pylit(seed_default)

        return self._render_module(body, ret, max_attempts, seed_lit)

    def _emit_node(self, node_id: str, node) -> list[str]:
        emitter = getattr(self, f"_emit_{node.type_id}", None)
        head = [f"    # {node.type_id}: {node_id}"]
        if emitter is not None:
            return head + emitter(node_id, node)
        return head + self._emit_generic(node_id, node)

    def _emit_generic(self, node_id: str, node) -> list[str]:
        """Универсальный путь: инстанцировать узел и вызвать .compute()."""
        # Собрать словарь входов из подключённых проводов.
        items = []
        for p in node.input_ports():
            expr = self._input_expr(node_id, p.name)
            if expr is not None:
                items.append(f"{p.name!r}: {expr}")
        inputs = "{" + ", ".join(items) + "}"
        tmp = f"_out_{_ident(node_id)}"
        lines = [
            f"    {tmp} = _node({node.type_id!r}, {node_id!r}, "
            f"{_pylit(dict(node.params))}).compute({inputs}, ctx)",
        ]
        for p in node.output_ports():
            lines.append(f"    {self._out_var(node_id, p.name)} = {tmp}[{p.name!r}]")
        return lines

    # ---- Инлайн-эмиттеры простых узлов ----

    def _emit_constant_number(self, node_id, node) -> list[str]:
        v = float(node.params.get("value", 0))
        return [f"    {self._out_var(node_id, 'out')} = {v!r}"]

    def _emit_constant_string(self, node_id, node) -> list[str]:
        v = str(node.params.get("value", ""))
        return [f"    {self._out_var(node_id, 'out')} = {v!r}"]

    def _emit_constant_bool(self, node_id, node) -> list[str]:
        v = str(node.params.get("value", "true")).lower() == "true"
        return [f"    {self._out_var(node_id, 'out')} = {v!r}"]

    def _emit_random_natural(self, node_id, node) -> list[str]:
        return self._emit_random(node_id, node, "natural")

    def _emit_random_real(self, node_id, node) -> list[str]:
        return self._emit_random(node_id, node, "real")

    def _emit_random(self, node_id, node, kind) -> list[str]:
        cfg = dict(node.params)
        cfg["kind"] = kind
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"_gen_value({node_id!r}, {_pylit(cfg)})"
        ]

    def _emit_var_dict(self, node_id, node) -> list[str]:
        names = node.params.get("names") or []
        pairs = []
        for n in names:
            expr = self._input_expr(node_id, str(n))
            pairs.append(f"{str(n)!r}: float({expr})")
        return [f"    {self._out_var(node_id, 'out')} = {{{', '.join(pairs)}}}"]

    def _emit_formula(self, node_id, node) -> list[str]:
        expr = node.params.get("expr", "")
        vars_expr = self._input_expr(node_id, "vars") or "{}"
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"_formula({node_id!r}, {expr!r}, {vars_expr})"
        ]

    def _emit_template(self, node_id, node) -> list[str]:
        text = node.params.get("text", "")
        vars_expr = self._input_expr(node_id, "vars") or "{}"
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"_template({text!r}, {vars_expr})"
        ]

    def _emit_text_block(self, node_id, node) -> list[str]:
        text_expr = self._input_expr(node_id, "text") or "''"
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"TextBlock(str({text_expr}))"
        ]

    def _emit_block_list(self, node_id, node) -> list[str]:
        parts = []
        for p in node.input_ports():
            expr = self._input_expr(node_id, p.name)
            if expr is not None:
                parts.append(expr)
        joined = ", ".join(parts)
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"[_b for _b in [{joined}] if _b is not None]"
        ]

    def _emit_static_task(self, node_id, node) -> list[str]:
        stmt = self._input_expr(node_id, "statement") or "[]"
        ans = self._input_expr(node_id, "answer") or "[]"
        return [
            f"    {self._out_var(node_id, 'out')} = "
            f"StaticTask(statement=list({stmt}), answer=list({ans}))"
        ]

    # ---------- Шаблон модуля ----------

    def _render_module(self, body, ret, max_attempts, seed_lit) -> str:
        body_src = "\n".join(body) if body else "    pass"
        return _MODULE_TEMPLATE.format(
            func=self.func_name,
            body=body_src,
            ret=ret,
            max_attempts=max_attempts,
            seed=seed_lit,
        )


_MODULE_TEMPLATE = '''"""
Авто-сгенерировано из графа задания (GraphCompiler).
Не редактируйте вручную — перегенерируйте из конструктора.

Запуск:
    from this_module import {func}
    task = {func}(seed=42)
"""

from __future__ import annotations
import math
import random

from core.graph.nodes import DEFAULT_REGISTRY as _REGISTRY
from core.graph.node import ExecContext as _Ctx
from core.graph.errors import RetryGeneration as _Retry
from core.blocks import TextBlock, FormulaBlock
from core.task import StaticTask


def _node(type_id, node_id, params):
    """Инстанцировать узел из реестра (универсальный путь компиляции)."""
    return _REGISTRY.create(type_id, node_id, params)


def _gen_value(node_id, cfg):
    """Случайное число по спецификации (как random_natural/random_real)."""
    from exercises.fisic.generation import generate_value, parse_variable_spec
    return generate_value(parse_variable_spec(node_id, cfg))


def _formula(node_id, expr, variables):
    """Безопасное вычисление формулы (как узел formula, с retry на inf/nan)."""
    from exercises.fisic.expression import evaluate_formula
    try:
        value = evaluate_formula(expr, variables or {{}})
    except (OverflowError, ValueError, ZeroDivisionError) as e:
        raise _Retry(f"Формула {{node_id!r}}: {{e}}")
    if math.isinf(value) or math.isnan(value):
        raise _Retry(f"Формула {{node_id!r}}: inf/nan.")
    return float(value)


def _template(text, variables):
    """Подстановка #имя# (как узел template)."""
    from exercises.fisic.formatting import format_number
    out = str(text)
    for name, value in (variables or {{}}).items():
        try:
            v = float(value)
            if abs(v - round(v)) < 1e-9:
                s = format_number(v, scientific_threshold_high=float("inf"))
            else:
                s = format_number(v)
        except (TypeError, ValueError):
            s = str(value)
        out = out.replace(f"#{{name}}#", s)
    return out


def _run(ctx):
{body}
    return {ret}


def {func}(seed={seed}, max_attempts={max_attempts}):
    """Сгенерировать задание. seed — для воспроизводимости."""
    if seed is not None:
        random.seed(seed)
    ctx = _Ctx(rng=random.Random(seed) if seed is not None else random.Random())
    last = None
    for _attempt in range(max_attempts):
        ctx.attempt = _attempt
        try:
            return _run(ctx)
        except _Retry as e:
            last = e
            continue
    raise RuntimeError(
        f"Не удалось сгенерировать задание за {max_attempts} попыток: {{last}}"
    )


if __name__ == "__main__":
    print({func}(seed=1))
'''


def compile_graph(spec, registry=None, func_name: str = "generate") -> str:
    """Удобная обёртка: GraphSpec/-dict → исходный текст Python-модуля."""
    if not isinstance(spec, GraphSpec):
        spec = GraphSpec.parse(spec)
    return GraphCompiler(spec, registry=registry, func_name=func_name).compile()
