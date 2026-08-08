"""
Финальный узел Июля со слотами ответа — этап 5 плана (§7.1).

Что здесь проверяется и почему именно это:

  * граф без узлов-обёрток «значение → блок» вообще собирает задание —
    иначе обещание «целый класс узлов исчезает из всех графов» пустое;
  * задание, собранное этим узлом, ПРОВЕРЯЕМО (`is_checkable`) — это стык
    этапов 1 и 5, ради которого порядок работ и был такой;
  * блоки ответа выводятся из спецификации, а не пишутся автором (§1);
  * объявление слота разбирается строго: молчаливое умолчание в правиле
    сравнения — это задание, принимающее не то, что задумано;
  * измеримое упрощение: тот же граф на старом и на новом финале,
    разница в числе узлов — не пожелание, а число.
"""

from __future__ import annotations

import unittest

from core.answers import (CheckMode, ExpressionSpec, NumberSpec, SlotsSpec,
                          TextSpec, ToleranceKind)
from core.graph.errors import GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.nodes import DEFAULT_REGISTRY
from core.graph.nodes.answer_slots import parse_slots
from core.graph.port_types import PortType
from core.graph.spec import GraphSpec
from core.task import StaticTask


def run_graph(spec: dict) -> StaticTask:
    return GraphExecutor(GraphSpec.parse(spec)).run()


def _compiled(spec: dict, *, seed: int) -> StaticTask:
    """Тот же граф, но через компилятор в Python-модуль."""
    from core.graph.compiler import compile_graph
    namespace: dict = {}
    exec(compile(compile_graph(spec), "<compiled-graph>", "exec"), namespace)
    return namespace["generate"](seed=seed)


# ======================================================================
#  Разбор объявления слота
# ======================================================================

class ParseSlotsTests(unittest.TestCase):

    def test_bare_name_is_a_number(self):
        """Умолчание — число: самый частый ответ не должен требовать слов."""
        (decl,) = parse_slots(["v"])
        self.assertEqual(decl.name, "v")
        self.assertEqual(decl.kind, "number")
        self.assertIs(decl.port_type, PortType.NUMBER)
        self.assertEqual(decl.label, "v")

    def test_kind_selects_port_type(self):
        kinds = {d.name: d.port_type for d in
                 parse_slots(["a:number", "b:expr", "c:text"])}
        self.assertEqual(kinds, {"a": PortType.NUMBER,
                                 "b": PortType.EXPR,
                                 "c": PortType.STRING})

    def test_options_reach_the_spec(self):
        (decl,) = parse_slots(["v:number:unit=м/с:abs=0.5:label=Скорость"])
        spec = decl.build(10.0, CheckMode.SOFT)
        self.assertIsInstance(spec, NumberSpec)
        self.assertEqual(spec.unit, "м/с")
        self.assertIs(spec.tolerance.kind, ToleranceKind.ABSOLUTE)
        self.assertEqual(spec.tolerance.amount, 0.5)
        self.assertEqual(decl.label, "Скорость")
        self.assertTrue(spec.check("10.4 м/с").accepted)
        self.assertFalse(spec.check("11 м/с").accepted)

    def test_significant_digits_shorten_the_shown_answer(self):
        """
        Показ обязан согласоваться с проверкой.

        Принимаем три значащие цифры — печатать 3.3333333333333335 нельзя:
        ученик решит, что от него ждут все цифры.
        """
        (decl,) = parse_slots(["v:number:sig=3"])
        spec = decl.build(10 / 3, CheckMode.SOFT)
        self.assertEqual(spec.written, "3.33")
        self.assertTrue(spec.check("3.33").accepted)

    def test_text_options(self):
        (decl,) = parse_slots(["city:text:alt=Moscow|Москва̀:case:typos=2"])
        spec = decl.build("Москва", CheckMode.SOFT)
        self.assertIsInstance(spec, TextSpec)
        self.assertEqual(spec.alternatives, ("Moscow", "Москва̀"))
        self.assertTrue(spec.case_sensitive)
        self.assertEqual(spec.max_edits, 2)

    def test_expression_options(self):
        (decl,) = parse_slots(["y:expr:vars=x:reject=(x-1)*(x+1)"])
        spec = decl.build("x**2 - 1", CheckMode.SOFT)
        self.assertIsInstance(spec, ExpressionSpec)
        self.assertEqual(spec.symbols, ("x",))
        self.assertEqual(spec.reject_equivalent_to, ("(x-1)*(x+1)",))

    def test_symbols_default_to_those_of_the_answer(self):
        """
        Без `vars=` имена берутся из самого ответа.

        Пустой список символов означал бы, что ввод с буквами не проходит
        разбор вовсе — то есть ответ-выражение молча становится
        непроверяемым. Это худший из возможных умолчаний.
        """
        import sympy
        x = sympy.Symbol("x")
        (decl,) = parse_slots(["y:expr"])
        spec = decl.build(x ** 2 - 1, CheckMode.SOFT)
        self.assertEqual(spec.symbols, ("x",))
        self.assertTrue(spec.check("x^2-1").accepted)

    def test_per_slot_mode_overrides_the_node(self):
        (decl,) = parse_slots(["y:expr:vars=x:mode=strict"])
        spec = decl.build("x**2 - 1", CheckMode.SOFT)
        self.assertIs(spec.mode, CheckMode.STRICT)

    # ---------- отказы ----------

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(GraphValidationError):
            parse_slots(["v:колбаса"])

    def test_unknown_option_is_refused(self):
        """
        `alt=` у числа — почти наверняка перепутанный вид слота. Промолчать
        значит оставить автора с проверкой не той, что он задумал.
        """
        with self.assertRaises(GraphValidationError):
            parse_slots(["v:number:alt=1|2"])

    def test_two_tolerances_are_refused(self):
        with self.assertRaises(GraphValidationError):
            parse_slots(["v:number:abs=1:rel=0.1"])

    def test_duplicate_slot_is_refused(self):
        with self.assertRaises(GraphValidationError):
            parse_slots(["v", "v:text"])

    def test_non_identifier_name_is_refused(self):
        # Имя слота становится именем порта, а порт адресуется в проводе.
        with self.assertRaises(GraphValidationError):
            parse_slots(["моя скорость"])

    def test_blank_lines_are_skipped(self):
        self.assertEqual(len(parse_slots(["v", "", "  ", "t"])), 2)


# ======================================================================
#  Узел в графе
# ======================================================================

_MULTIPLY = {
    "nodes": [
        {"id": "a", "type": "random_natural", "params": {"min": 2, "max": 9}},
        {"id": "b", "type": "random_natural", "params": {"min": 2, "max": 9}},
        {"id": "f", "type": "formula", "params": {"expr": "a * b"}},
        {"id": "t", "type": "task", "params": {
            "statement": "Сколько будет #a# × #b#?",
            "slots": ["p:number:unit=шт"],
        }},
    ],
    "edges": [
        {"from": "a:out", "to": "f:a"}, {"from": "b:out", "to": "f:b"},
        {"from": "a:out", "to": "t:a"}, {"from": "b:out", "to": "t:b"},
        {"from": "f:out", "to": "t:p"},
    ],
    "meta": {"seed": 7},
}


class TaskNodeTests(unittest.TestCase):

    def test_graph_without_block_wrappers_produces_a_task(self):
        task = run_graph(_MULTIPLY)
        self.assertIsInstance(task, StaticTask)
        self.assertEqual(len(task.statement), 1)
        self.assertIn("×", task.statement[0].render_plain())

    def test_the_task_is_checkable(self):
        """Стык этапов 1 и 5: граф выдал задание, которое умеет проверять."""
        task = run_graph(_MULTIPLY)
        self.assertTrue(task.is_checkable)
        self.assertIsInstance(task.answer_spec, NumberSpec)
        self.assertEqual(task.answer_spec.unit, "шт")

    def test_answer_blocks_are_derived_from_the_spec(self):
        """
        Автор не писал текст ответа — он объявил слот. Совпадение показа с
        принимаемым значением тут не совпадение, а следствие: и то и другое
        сделано из одной спецификации.
        """
        task = run_graph(_MULTIPLY)
        shown = task.answer[0].render_plain()
        self.assertIn(shown.split()[0], task.answer_spec.accepted_examples()[0])
        self.assertTrue(task.answer_spec.check(shown).accepted)

    def test_no_slots_means_no_spec(self):
        """
        Задание без объявленного ответа — законное (открытый вопрос).
        Оно просто не проверяется, и врать про это нельзя.
        """
        task = run_graph({
            "nodes": [{"id": "t", "type": "task",
                       "params": {"statement": "Объясните, почему небо синее."}}],
            "edges": [],
        })
        self.assertFalse(task.is_checkable)
        self.assertEqual(task.answer, [])

    def test_ports_follow_the_declaration(self):
        node = DEFAULT_REGISTRY.create("task", "t", {
            "statement": "Дано #m# кг и #a# м/с².",
            "slots": ["F:number:unit=Н", "name:text"],
        })
        ports = {p.name: p for p in node.input_ports()}
        self.assertEqual(ports["F"].type, PortType.NUMBER)
        self.assertEqual(ports["name"].type, PortType.STRING)
        self.assertEqual(ports["m"].type, PortType.ANY)
        self.assertEqual(ports["a"].type, PortType.ANY)
        # Слоты обязательны — задание без ответа собралось бы молча.
        self.assertTrue(ports["F"].required)
        self.assertFalse(ports["m"].required)

    def test_slot_colliding_with_a_statement_marker_is_refused(self):
        """Иначе задание печатало бы собственный ответ в условии."""
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("task", "t", {
                "statement": "Скорость равна #v#.", "slots": ["v"]})

    def test_extra_blocks_join_the_statement(self):
        task = run_graph({
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 5}},
                {"id": "s", "type": "constant_string",
                 "params": {"value": "подсказка"}},
                {"id": "tb", "type": "text_block"},
                {"id": "t", "type": "task", "params": {
                    "statement": "Условие.", "slots": ["v"]}},
            ],
            "edges": [
                {"from": "s:out", "to": "tb:text"},
                {"from": "tb:out", "to": "t:blocks"},
                {"from": "n:out", "to": "t:v"},
            ],
        })
        self.assertEqual([b.render_plain() for b in task.statement],
                         ["Условие.", "подсказка"])


class LayoutTests(unittest.TestCase):
    """Раскладка ответа — то, что §11 называет «выбором раскладки»."""

    GRAPH = {
        "nodes": [
            {"id": "n", "type": "constant_number", "params": {"value": 3.5}},
            {"id": "s", "type": "constant_string", "params": {"value": "Москва"}},
            {"id": "t", "type": "task", "params": {
                "statement": "Найдите длину и город.",
                "slots": ["v:number:unit=м:label=Длина", "city:text"],
                "answer_template": "Длина #v#, город #city#.",
            }},
        ],
        "edges": [{"from": "n:out", "to": "t:v"},
                  {"from": "s:out", "to": "t:city"}],
    }

    def _answer(self, layout: str):
        spec = {**self.GRAPH}
        spec["nodes"] = [dict(n) for n in self.GRAPH["nodes"]]
        spec["nodes"][-1]["params"] = {**self.GRAPH["nodes"][-1]["params"],
                                       "layout": layout}
        return [b.render_plain() for b in run_graph(spec).answer]

    def test_lines_gives_a_block_per_slot(self):
        self.assertEqual(self._answer("lines"),
                         ["Длина = 3.5 м", "city = Москва"])

    def test_inline_gives_one_block(self):
        self.assertEqual(self._answer("inline"),
                         ["Длина = 3.5 м, city = Москва"])

    def test_template_substitutes_slots_into_the_authors_text(self):
        self.assertEqual(self._answer("template"),
                         ["Длина 3.5 м, город Москва."])

    def test_single_slot_without_a_label_shows_only_the_value(self):
        task = run_graph({
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 42}},
                {"id": "t", "type": "task",
                 "params": {"statement": "?", "slots": ["s:number:unit=м"]}},
            ],
            "edges": [{"from": "n:out", "to": "t:s"}],
        })
        self.assertEqual([b.render_plain() for b in task.answer], ["42 м"])

    def test_unknown_layout_is_refused(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("task", "t", {"layout": "карусель"})


class CheckModeTests(unittest.TestCase):
    """Переключатель преподавателя из §5.1 доходит до графа."""

    def _spec(self, check_mode: str):
        return run_graph({
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "x**2 - 1"}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Упростите (x-1)(x+1).",
                    "slots": ["y:expr:vars=x"],
                    "check_mode": check_mode,
                }},
            ],
            "edges": [{"from": "e:out", "to": "t:y"}],
        }).answer_spec

    def test_soft_accepts_an_equivalent_form(self):
        self.assertTrue(self._spec("soft").check("(x-1)*(x+1)").accepted)

    def test_strict_demands_the_written_form(self):
        strict = self._spec("strict")
        self.assertIs(strict.mode, CheckMode.STRICT)
        self.assertFalse(strict.check("(x-1)*(x+1)").accepted)
        self.assertTrue(strict.check("x^2-1").accepted)

    def test_rejected_form_survives_the_soft_mode(self):
        """
        Главная опасность §5: «упростите» с мягкой проверкой принимает само
        условие обратно. Отвергаемая форма объявляется в том же слоте.
        """
        spec = run_graph({
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "x**2 - 1"}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Упростите (x-1)(x+1).",
                    "slots": ["y:expr:vars=x:reject=(x-1)*(x+1)"],
                }},
            ],
            "edges": [{"from": "e:out", "to": "t:y"}],
        }).answer_spec
        self.assertFalse(spec.check("(x-1)*(x+1)").accepted)
        self.assertTrue(spec.check("x^2-1").accepted)

    def test_several_slots_become_one_slots_spec(self):
        task = run_graph(LayoutTests.GRAPH)
        self.assertIsInstance(task.answer_spec, SlotsSpec)
        self.assertEqual([name for name, _ in task.answer_spec.slots],
                         ["v", "city"])


class CrossingTheProcessBoundaryTests(unittest.TestCase):
    """
    Этап 4 вынес исполнение графа в отдельный процесс, поэтому задание
    ездит туда-обратно словарём. Спецификация обязана это пережить —
    иначе изолированный путь молча отдавал бы непроверяемое задание.
    """

    def test_round_trip_keeps_the_spec(self):
        task = run_graph(_MULTIPLY)
        restored = StaticTask.from_dict(task.to_dict())
        self.assertTrue(restored.is_checkable)
        self.assertEqual(restored.answer_spec.to_dict(),
                         task.answer_spec.to_dict())

    def test_compatible_widgets_travel_with_the_task(self):
        payload = run_graph(_MULTIPLY).to_dict()
        self.assertTrue(payload["is_checkable"])
        self.assertTrue(payload["widgets"])

    def test_compiler_handles_the_node(self):
        """
        Компилятор графа разворачивает узлы в Python. Для `task`
        отдельного эмиттера нет — он идёт универсальным путём, и это
        нужно подтвердить, а не предположить.
        """
        task = _compiled(_MULTIPLY, seed=7)
        self.assertTrue(task.is_checkable)
        self.assertEqual(task.answer_spec.unit, "шт")

    def test_compiler_agrees_with_the_executor_on_every_example(self):
        """
        Компилятор — вторая реализация того же языка, и расходиться она
        имеет право только явно. Проверяем совпадение результата на всём
        каталоге примеров: молчаливое расхождение означало бы граф,
        который работает в редакторе и врёт после компиляции.
        """
        from exercises.graph_examples.examples import EXAMPLES
        for name, entry in EXAMPLES.items():
            with self.subTest(example=name):
                graph = dict(entry["graph"])
                graph["meta"] = {**graph.get("meta", {}), "seed": 5}
                direct = run_graph(graph)
                compiled = _compiled(graph, seed=5)
                self.assertEqual(
                    [b.render_plain() for b in direct.statement + direct.answer],
                    [b.render_plain()
                     for b in compiled.statement + compiled.answer])


class MeasuredSimplificationTests(unittest.TestCase):
    """
    Обещание §7.1 — «целый класс узлов исчезает из всех графов разом» —
    проверяемо счётом, а не на слово.
    """

    OLD = {
        "nodes": [
            {"id": "a", "type": "random_natural", "params": {"min": 2, "max": 9}},
            {"id": "b", "type": "random_natural", "params": {"min": 2, "max": 9}},
            {"id": "f", "type": "formula", "params": {"expr": "a * b"}},
            {"id": "cond", "type": "text",
             "params": {"text": "Сколько будет #a# × #b#?"}},
            {"id": "ans", "type": "text", "params": {"text": "#p# шт"}},
            {"id": "task", "type": "static_task"},
        ],
        "edges": [
            {"from": "a:out", "to": "f:a"}, {"from": "b:out", "to": "f:b"},
            {"from": "a:out", "to": "cond:a"}, {"from": "b:out", "to": "cond:b"},
            {"from": "f:out", "to": "ans:p"},
            {"from": "cond:out", "to": "task:statement"},
            {"from": "ans:out", "to": "task:answer"},
        ],
        "meta": {"seed": 7},
    }

    def test_same_task_with_two_nodes_fewer(self):
        old, new = run_graph(self.OLD), run_graph(_MULTIPLY)
        self.assertEqual(old.statement[0].render_plain(),
                         new.statement[0].render_plain())
        self.assertEqual(old.answer[0].render_plain(),
                         new.answer[0].render_plain())
        self.assertEqual(len(self.OLD["nodes"]) - len(_MULTIPLY["nodes"]), 2)
        self.assertEqual(len(self.OLD["edges"]) - len(_MULTIPLY["edges"]), 2)

    def test_and_the_old_one_cannot_be_checked_at_all(self):
        """
        Главная разница не в двух узлах. Старый граф выдаёт отрендеренный
        текст, из которого проверку не восстановить, — ровно то, с чего
        начинается §1.
        """
        self.assertFalse(run_graph(self.OLD).is_checkable)
        self.assertTrue(run_graph(_MULTIPLY).is_checkable)


class ExistingGraphsKeepWorkingTests(unittest.TestCase):
    """Сохранённые графы лежат у пользователей — их никто не переписывал."""

    def test_static_task_still_assembles(self):
        task = run_graph(MeasuredSimplificationTests.OLD)
        self.assertIsInstance(task, StaticTask)
        self.assertEqual(len(task.statement), 1)

    def test_catalog_examples_all_still_run(self):
        from exercises.graph_examples.examples import EXAMPLES
        for name, entry in EXAMPLES.items():
            with self.subTest(example=name):
                self.assertIsInstance(run_graph(entry["graph"]), StaticTask)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class MatrixSlotTests(unittest.TestCase):
    """
    Матрица в слоте ответа — то, чего не хватало линейной алгебре.

    Отдельного вида ответа под неё не заведено: `matrix` строит тот же
    набор слотов, только с объявленной формой. Поэтому и опции у слота
    числовые — допуск применяется к каждой ячейке.
    """

    GRAPH = {
        "nodes": [
            {"id": "m", "type": "matrix_const", "params": {"data": "1,2;3,4"}},
            {"id": "d", "type": "matrix_transpose"},
            {"id": "t", "type": "task", "params": {
                "statement": "Транспонируйте матрицу.",
                "slots": ["A:matrix"]}},
        ],
        "edges": [{"from": "m:out", "to": "d:in"},
                  {"from": "d:out", "to": "t:A"}],
    }

    def test_matrix_slot_makes_the_task_checkable(self):
        task = run_graph(self.GRAPH)
        self.assertTrue(task.is_checkable)
        self.assertEqual(task.answer_spec.shape, (2, 2))

    def test_port_is_typed_as_a_matrix(self):
        node = DEFAULT_REGISTRY.create("task", "t", {"slots": ["A:matrix"]})
        ports = {p.name: p for p in node.input_ports()}
        self.assertEqual(ports["A"].type, PortType.MATRIX)

    def test_answer_is_checked_cell_by_cell(self):
        spec = run_graph(self.GRAPH).answer_spec
        self.assertTrue(spec.check_slots(
            {"r1c1": "1", "r1c2": "3", "r2c1": "2", "r2c2": "4"}).accepted)
        wrong = spec.check_slots(
            {"r1c1": "1", "r1c2": "3", "r2c1": "9", "r2c2": "4"})
        self.assertFalse(wrong.accepted)
        self.assertIn("строка 2, столбец 1", wrong.detail)

    def test_tolerance_reaches_every_cell(self):
        graph = {
            "nodes": [
                {"id": "m", "type": "matrix_const",
                 "params": {"data": "1.0,2.0"}},
                {"id": "t", "type": "task", "params": {
                    "statement": "?", "slots": ["A:matrix:abs=0.1"]}},
            ],
            "edges": [{"from": "m:out", "to": "t:A"}],
        }
        spec = run_graph(graph).answer_spec
        self.assertTrue(spec.check_slots({"r1c1": "1.05", "r1c2": "2"}).accepted)

    def test_non_matrix_value_is_refused_loudly(self):
        graph = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 5}},
                {"id": "t", "type": "task", "params": {
                    "statement": "?", "slots": ["A:matrix"]}},
            ],
            "edges": [{"from": "n:out", "to": "t:A"}],
        }
        # Порт объявлен MATRIX, поэтому провод от числа не соединяется —
        # ошибка ловится на сборке графа, а не при генерации.
        with self.assertRaises(GraphValidationError):
            run_graph(graph)

    def test_matrix_slot_refuses_text_options(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("task", "t", {"slots": ["A:matrix:alt=1"]})

    def test_the_grid_crosses_the_process_boundary(self):
        task = run_graph(self.GRAPH)
        restored = StaticTask.from_dict(task.to_dict())
        self.assertEqual(restored.answer_spec.shape, (2, 2))


class ListSlotTests(unittest.TestCase):
    """
    `много` — слот, число полей в котором приносят ДАННЫЕ.

    Понадобилось на «вставьте пропущенные слова»: у одного предложения
    один пропуск, у другого три, а объявление слотов одно на все выпуски
    задания. До этого такое задание нельзя было собрать типизированно
    вообще — и оно существовало блоками, которые ничего не проверяют.

    Новой сущности здесь опять нет: несколько именованных полей — это
    `SlotsSpec`, тот же, что обслуживает матрицу. Списочный слот
    добавляет к нему ровно одно свойство.
    """

    def _run(self, values, slot="п:text:много"):
        return run_graph({
            "nodes": [
                {"id": "l", "type": "string_list",
                 "params": {"items": values}},
                {"id": "t", "type": "task",
                 "params": {"statement": "?", "slots": [slot]}},
            ],
            "edges": [{"from": "l:out", "to": "t:п"}],
        })

    def test_the_flag_needs_no_value(self):
        (decl,) = parse_slots(["п:text:много"])
        self.assertTrue(decl.many)
        self.assertEqual(decl.kind, "text")

    def test_the_port_takes_a_list(self):
        node = DEFAULT_REGISTRY.create("task", "t", {"slots": ["п:text:много"]})
        ports = {p.name: p for p in node.input_ports()}
        self.assertEqual(ports["п"].type, PortType.LIST)

    def test_a_plain_slot_is_untouched(self):
        (decl,) = parse_slots(["п:text"])
        self.assertFalse(decl.many)
        self.assertIs(decl.port_type, PortType.STRING)

    def test_fields_follow_the_data(self):
        """Объявление одно, а полей столько, сколько принесли."""
        for values in (["a"], ["a", "b"], ["a", "b", "c", "d"]):
            with self.subTest(values=values):
                spec = self._run(values).answer_spec
                self.assertEqual(len(spec.input_fields()), len(values))

    def test_names_are_numbered_from_one(self):
        spec = self._run(["a", "b"]).answer_spec
        self.assertEqual([f.name for f in spec.input_fields()], ["п1", "п2"])

    def test_every_field_is_checked(self):
        spec = self._run(["раз", "два"]).answer_spec
        self.assertTrue(spec.check_slots({"п1": "раз", "п2": "два"}).accepted)
        self.assertFalse(spec.check_slots({"п1": "раз", "п2": "три"}).accepted)

    def test_options_reach_every_field(self):
        """Опция вида описывает ЭЛЕМЕНТ, а не список целиком."""
        spec = self._run(["Москва"], slot="п:text:много:alt=Moscow").answer_spec
        self.assertTrue(spec.check_slots({"п1": "Moscow"}).accepted)

    def test_numbers_work_too(self):
        """`много` — общая опция, а не свойство строк."""
        spec = self._run([1, 2, 3], slot="п:number:много:abs=0.5").answer_spec
        self.assertTrue(spec.check_slots(
            {"п1": "1.2", "п2": "2", "п3": "3"}).accepted)

    def test_there_is_no_grid(self):
        """
        Пропуски идут подряд, а не сеткой. Форма 1×N сказала бы клиенту
        «рисуй таблицу» там, где таблицы нет.
        """
        self.assertIsNone(self._run(["a", "b"]).answer_spec.shape)

    def test_a_single_value_is_refused(self):
        with self.assertRaises(GraphValidationError):
            run_graph({
                "nodes": [
                    {"id": "c", "type": "constant_string",
                     "params": {"value": "раз"}},
                    {"id": "t", "type": "task",
                     "params": {"statement": "?", "slots": ["п:text:много"]}},
                ],
                "edges": [{"from": "c:out", "to": "t:п"}],
            })

    def test_an_empty_list_is_not_a_task(self):
        """
        Пустой список — повод перегенерировать, а не упасть на сборке:
        отличить «список пуст всегда» от «пуст в этот раз» на этапе
        разбора нельзя. Причина обязана дожить до итогового сообщения,
        иначе автор увидит только «не удалось за 100 попыток».
        """
        from core.graph.errors import GraphError
        with self.assertRaises(GraphError) as caught:
            self._run([])
        self.assertIn("пустой список", str(caught.exception))

    def test_no_test_port_for_a_list_slot(self):
        """
        Тестом задаётся вопрос целиком, а не отдельное поле из
        нескольких: неверные варианты тут вешать не на что.
        """
        node = DEFAULT_REGISTRY.create(
            "task", "t", {"slots": ["п:text:много:choices=4"]})
        self.assertNotIn("п_wrong", [p.name for p in node.input_ports()])

    def test_the_list_slot_crosses_the_process_boundary(self):
        task = self._run(["раз", "два"])
        restored = StaticTask.from_dict(task.to_dict())
        self.assertTrue(restored.answer_spec.check_slots(
            {"п1": "раз", "п2": "два"}).accepted)
