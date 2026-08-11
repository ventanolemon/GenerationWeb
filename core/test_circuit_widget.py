"""
Холст логической схемы: то, что от него требуется на стороне ядра.

Холст — виджет ОТВЕТА, а не новый вид ответа (interactive_tasks_plan,
§3 и §7.3). Отсюда всё, что проверяется здесь: ядро не знает про SVG и
про клики, оно обязано лишь назвать виджет, отдать алфавит входов и
принять ту же строку, которую студент написал бы руками. Если это так,
холст не требует ни своего протокола, ни своей проверки.

Запуск:
    python -m unittest core.test_circuit_widget
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.answers import LogicSpec  # noqa: E402
from core.graph.errors import GraphValidationError  # noqa: E402
from core.graph.executor import GraphExecutor  # noqa: E402
from core.graph.spec import GraphSpec  # noqa: E402
from core.interactive import session_from_task  # noqa: E402
from core.widgets import registry, resolve_widget, widgets_for  # noqa: E402

VARIABLES = ("A", "B", "C")
FUNCTION = "(not(A) v (B ^ C))"


def _spec():
    return LogicSpec(value=FUNCTION, variables=VARIABLES)


class RegistryTests(unittest.TestCase):
    def test_canvas_serves_logic(self):
        widget = registry.get("circuit_canvas")
        self.assertIsNotNone(widget)
        self.assertTrue(widget.serves(_spec()))

    def test_canvas_does_not_serve_anything_else(self):
        """
        Холст схем осмыслен ровно для схем. Обслуживать им число или
        строку значило бы предложить автору заведомо неработающий выбор.
        """
        from core.answers import NumberSpec, TextSpec

        widget = registry.get("circuit_canvas")
        self.assertFalse(widget.serves(NumberSpec(value=1)))
        self.assertFalse(widget.serves(TextSpec(value="да")))

    def test_typing_stays_the_default(self):
        """
        Собирать схему мышью дольше, чем написать формулу, и навязывать
        это всем заданиям неправильно. Холст включается автором явно.
        """
        self.assertEqual(resolve_widget(_spec()).name, "text_input")
        self.assertEqual(resolve_widget(_spec(), "circuit_canvas").name,
                         "circuit_canvas")

    def test_canvas_is_among_compatible(self):
        self.assertIn("circuit_canvas", [w.name for w in widgets_for(_spec())])


class TokensTests(unittest.TestCase):
    """Алфавит для собирающего виджета."""

    def test_field_carries_the_input_names(self):
        field = _spec().input_fields()[0]
        self.assertEqual(field.tokens, VARIABLES)
        self.assertEqual(field.to_dict()["tokens"], list(VARIABLES))

    def test_tokens_are_absent_when_empty(self):
        # Пустое поле в ответе клиента — лишний ключ, который придётся
        # объяснять. Форма словаря та же, что у остальных полей.
        from core.answers import InputField

        self.assertNotIn("tokens", InputField(kind="text").to_dict())

    def test_tokens_do_not_leak_the_answer(self):
        """
        Главное свойство `InputField`: описание полей едет студенту, а
        спецификация — нет. Имена входов и так подписаны на чертеже.
        """
        field = _spec().input_fields()[0]
        self.assertNotIn("^", "".join(field.tokens))
        self.assertNotIn("not", "".join(field.tokens))
        self.assertNotIn(FUNCTION, field.to_dict().get("hint", ""))


class SlotKindMappingTests(unittest.TestCase):
    """
    Настоящий дефект, пойманный при подключении холста.

    `TaskNode` сверяет вид слота с видами виджета через карту, в которой
    были только number/expr/text. Виды `logic`, `output` и `equation`,
    появившиеся вместе с моделями, туда не попали — и любое задание с
    заданным виджетом падало голым `KeyError` при сборке графа. Автор
    графа увидел бы внутреннюю ошибку вместо внятного отказа.
    """

    @staticmethod
    def _graph(slot: str, widget: str):
        return {"nodes": [
            {"id": "m", "type": "model_opvs_circuit", "params": {"inputs": 3}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": [slot], "widget": widget}},
        ], "edges": [{"from": "m:expr", "to": "t:ответ"}]}

    def test_new_slot_kinds_do_not_crash_the_node(self):
        for slot, widget in (("ответ:logic", "circuit_canvas"),
                             ("ответ:logic", "text_input")):
            with self.subTest(slot=slot, widget=widget):
                GraphExecutor(GraphSpec.parse(self._graph(slot, widget)))

    def test_incompatible_pair_is_refused_by_name(self):
        """Отказ обязан называть и вид ответа, и что виджет умеет."""
        with self.assertRaises(GraphValidationError) as ctx:
            GraphExecutor(GraphSpec.parse(
                self._graph("ответ:logic", "slot_fields")))
        message = str(ctx.exception)
        self.assertIn("не обслуживает", message)
        self.assertIn("logic", message)
        self.assertIn("slot_fields", message)

    def test_canvas_is_refused_for_a_number(self):
        graph = {"nodes": [
            {"id": "c", "type": "constant_number", "params": {"value": 5}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": ["ответ:number"],
                "widget": "circuit_canvas"}},
        ], "edges": [{"from": "c:out", "to": "t:ответ"}]}
        with self.assertRaises(GraphValidationError):
            GraphExecutor(GraphSpec.parse(graph))


class CanvasTaskTests(unittest.TestCase):
    """Задание «соберите схему» целиком."""

    GRAPH = {"nodes": [
        {"id": "m", "type": "model_opvs_circuit", "params": {"inputs": 3}},
        {"id": "b", "type": "image_block", "params": {"caption": "Схема"}},
        {"id": "t", "type": "task", "params": {
            "statement": "Соберите схему, реализующую ту же функцию.",
            "slots": ["ответ:logic"], "widget": "circuit_canvas"}},
    ], "edges": [
        {"from": "m:image", "to": "b:in"},
        {"from": "b:out", "to": "t:blocks"},
        {"from": "m:expr", "to": "t:ответ"},
    ]}

    def _session(self):
        task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
        return task, session_from_task(task)

    def test_widget_reaches_the_client(self):
        _, session = self._session()
        self.assertEqual(session.questions[0].widget_name(), "circuit_canvas")

    def test_client_gets_the_alphabet(self):
        _, session = self._session()
        field = session.questions[0].spec.input_fields()[0]
        self.assertEqual(list(field.tokens), ["A", "B", "C"])

    def test_assembled_answer_is_checked_by_the_usual_path(self):
        """
        Холст отдаёт ТУ ЖЕ строку, что и клавиатура, — значит проверять
        его нечем особенным. Ради этого он и устроен так.
        """
        task, session = self._session()
        self.assertTrue(session.submit(task.answer_spec.value).correct)

    def test_another_wiring_of_the_same_function_is_accepted(self):
        """
        Схему можно собрать иначе и получить ту же функцию — сравниваются
        ФУНКЦИИ, а не чертежи. Без этого холст был бы бесполезен:
        совпасть с эталоном проводом в провод почти невозможно.
        """
        task, session = self._session()
        from sympy.logic.boolalg import simplify_logic

        from core.boolean_text import format_boolean, parse_boolean

        minimal = format_boolean(simplify_logic(
            parse_boolean(task.answer_spec.value, ["A", "B", "C"])))
        self.assertTrue(session.submit(minimal).correct)

    def test_a_wrong_circuit_is_refused(self):
        _, session = self._session()
        self.assertFalse(session.submit("A").correct)


if __name__ == "__main__":
    unittest.main()
