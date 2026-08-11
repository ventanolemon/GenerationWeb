"""
Логическая схема как модель — и проверка ответа по существу.

Здесь стандарт впервые окупается делом. Раньше «выпишите функцию по
схеме» было непроверяемым: ответ жил в текстовом блоке «Логическая
функция: …», а правильных записей у одной функции бесконечно много.
Теперь функция — величина, и ответ сравнивается ФУНКЦИЯМИ, а не строками:
`not(A) v (B ^ C)`, `¬A ∨ BC` и `!A + B*C` — один ответ.

Запуск:
    python -m unittest core.test_opvs_model
"""

from __future__ import annotations

import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sympy as sp  # noqa: E402
from sympy.logic.boolalg import Xor, simplify_logic  # noqa: E402

from core.boolean_text import (  # noqa: E402
    BooleanTextError, boolean_equivalent, parse_boolean,
)
from core.models.opvs_circuit import MODEL as CIRCUIT  # noqa: E402

SEEDS = range(25)
V3 = ["A", "B", "C"]


def _instance(seed: int, **params):
    return CIRCUIT.build(random.Random(seed), **({"inputs": 3} | params))


class NotationTests(unittest.TestCase):
    """Три обиходные системы обозначений читаются одинаково."""

    REFERENCE = "not(A) v (B ^ C)"
    SAME = ["¬A ∨ BC", "!A + B*C", "not A or B and C", "~A|(B&C)",
            "не A или C и B", "NOT(A) V (C ^ B)", "(not A) v (B C)"]

    def test_all_spellings_give_one_function(self):
        reference = parse_boolean(self.REFERENCE, V3)
        for text in self.SAME:
            with self.subTest(text=text):
                self.assertFalse(
                    sp.satisfiable(Xor(reference, parse_boolean(text, V3))),
                    "разные записи одной функции прочитаны по-разному")

    def test_and_binds_tighter_than_or(self):
        self.assertTrue(boolean_equivalent(parse_boolean("A v B ^ C", V3),
                                           "A v (B ^ C)", V3))
        self.assertFalse(boolean_equivalent(parse_boolean("A v B ^ C", V3),
                                            "(A v B) ^ C", V3))

    def test_not_binds_tighter_than_and(self):
        self.assertTrue(boolean_equivalent(parse_boolean("not A ^ B", V3),
                                           "(not A) ^ B", V3))

    def test_juxtaposition_means_and(self):
        # `AB` в учебнике — конъюнкция; отказывать было бы придирчивостью.
        self.assertTrue(boolean_equivalent(parse_boolean("AB", V3),
                                           "A ^ B", V3))

    def test_caret_is_conjunction_not_xor(self):
        """
        Ровно то, из-за чего разборщик написан свой. `sympify` прочитал бы
        `A ^ B` как исключающее ИЛИ — и МОЛЧА: студент получил бы
        «неправильно» за правильный ответ.
        """
        a, b = sp.Symbol("A"), sp.Symbol("B")
        self.assertEqual(parse_boolean("A ^ B", V3), sp.And(a, b))
        self.assertNotEqual(parse_boolean("A ^ B", V3), Xor(a, b))


class BadInputTests(unittest.TestCase):
    def test_unknown_variable_is_named(self):
        with self.assertRaises(BooleanTextError) as ctx:
            parse_boolean("Q v A", V3)
        self.assertIn("Q", str(ctx.exception))

    def test_unbalanced_bracket_is_refused(self):
        with self.assertRaises(BooleanTextError):
            parse_boolean("(A v B", V3)

    def test_trailing_operator_is_refused(self):
        with self.assertRaises(BooleanTextError):
            parse_boolean("A v", V3)

    def test_empty_is_refused(self):
        with self.assertRaises(BooleanTextError):
            parse_boolean("   ", V3)

    def test_garbage_is_not_equivalent_to_anything(self):
        # Отказ разбора — это «неверно», а не исключение наружу.
        self.assertFalse(boolean_equivalent(parse_boolean("A", V3), "хрю", V3))

    def test_nothing_is_executed(self):
        """
        Разбор не исполняет питон — иначе ответ студента был бы
        исполняемым кодом на сервере.
        """
        for text in ("__import__('os')", "1/0", "A.__class__"):
            with self.subTest(text=text), self.assertRaises(BooleanTextError):
                parse_boolean(text, V3)


class ModelValuesTests(unittest.TestCase):
    def test_formula_and_expr_describe_the_same_function(self):
        """
        Строка и выражение — две записи одного, и расхождение между ними
        означало бы, что студенту показывают одно, а проверяют другое.
        """
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertTrue(boolean_equivalent(
                    instance.values["expr"], instance.values["formula"],
                    instance.values["variables"]))

    def test_simplified_is_the_same_function(self):
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertFalse(sp.satisfiable(Xor(
                    instance.values["expr"], instance.values["simplified"])))

    def test_truth_table_matches_the_expression(self):
        """Таблица считается независимо от того, как её считает модель."""
        for seed in SEEDS:
            instance = _instance(seed)
            names = instance.values["variables"]
            symbols = [sp.Symbol(n) for n in names]
            for row in instance.values["truth_table"]:
                assignment = dict(zip(symbols, [bool(v) for v in row[:-1]]))
                with self.subTest(seed=seed, row=row):
                    self.assertEqual(
                        bool(instance.values["expr"].subs(assignment)),
                        bool(row[-1]))

    def test_table_has_a_row_per_assignment(self):
        for inputs in (3, 4):
            instance = _instance(1, inputs=inputs)
            with self.subTest(inputs=inputs):
                self.assertEqual(len(instance.values["truth_table"]),
                                 2 ** inputs)
                self.assertEqual(len(instance.values["variables"]), inputs)

    def test_ones_counts_the_true_rows(self):
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertEqual(
                    instance.values["ones"],
                    sum(row[-1] for row in instance.values["truth_table"]))

    def test_function_is_neither_constant(self):
        # Тавтология и противоречие как задание бессмысленны.
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertGreater(instance.values["ones"], 0)
                self.assertLess(instance.values["ones"],
                                2 ** len(instance.values["variables"]))

    def test_every_drawn_input_matters(self):
        """
        Вход, нарисованный на схеме, обязан влиять на выход — иначе в
        таблице появляется столбец, от которого ничего не зависит.
        """
        for seed in SEEDS:
            instance = _instance(seed)
            used = {str(s)
                    for s in simplify_logic(instance.values["expr"]).free_symbols}
            with self.subTest(seed=seed):
                self.assertEqual(set(instance.values["variables"]) - used, set())

    def test_image_is_a_picture_not_a_block(self):
        # Тип IMAGE в языке — это PIL.Image; подпись навешивает image_block.
        image = _instance(2).blocks["image"]
        self.assertTrue(hasattr(image, "size"))
        self.assertGreater(image.size[0], 0)


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_gives_the_same_circuit(self):
        """
        Генератор берёт случайность из глобального random — модель обязана
        всё равно быть воспроизводимой от переданного rng.
        """
        first = _instance(9).values["formula"]
        second = _instance(9).values["formula"]
        self.assertEqual(first, second)

    def test_global_random_is_left_alone(self):
        """
        Исполнитель графа сеет глобальный random один раз на попытку.
        Сбить его посреди исполнения значило бы изменить результат
        соседних узлов — модель обязана вернуть состояние на место.
        """
        random.seed(1234)
        expected = [random.random() for _ in range(3)]
        random.seed(1234)
        _instance(5)
        self.assertEqual([random.random() for _ in range(3)], expected)

    def test_different_seeds_give_different_circuits(self):
        seen = {_instance(seed).values["formula"] for seed in SEEDS}
        self.assertGreater(len(seen), len(SEEDS) // 2)


class EquivalenceTests(unittest.TestCase):
    """Первый настоящий потребитель `Instance.equivalent`."""

    def test_the_students_own_wording_is_accepted(self):
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertTrue(
                    instance.equivalent("expr", instance.values["formula"]))

    def test_the_simplified_form_is_accepted(self):
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertTrue(
                    instance.equivalent("expr", instance.values["simplified"]))

    def test_a_different_function_is_rejected(self):
        for seed in SEEDS:
            instance = _instance(seed)
            wrong = sp.Not(instance.values["expr"])
            with self.subTest(seed=seed):
                self.assertFalse(instance.equivalent("expr", wrong))

    def test_answer_in_another_notation_is_accepted(self):
        instance = _instance(0)
        text = str(instance.values["formula"])
        alternative = (text.replace("^", "&").replace(" v ", " | ")
                       .replace("not", "~"))
        self.assertTrue(instance.equivalent("expr", alternative),
                        f"{alternative!r} не принято")

    def test_extra_variable_is_rejected(self):
        # `A v Q` — не «другая запись», а ответ про другую схему.
        instance = _instance(0)
        self.assertFalse(instance.equivalent("expr", "A v Q"))

    def test_non_function_values_use_the_default_rule(self):
        instance = _instance(0)
        self.assertTrue(instance.equivalent("ones", instance.values["ones"]))
        self.assertFalse(instance.equivalent("ones",
                                             instance.values["ones"] + 1))


class LogicSpecTests(unittest.TestCase):
    """
    Спецификация ответа-функции: то, чем `equivalent` доходит до конвейера.

    Отдельный вид ответа понадобился потому, что `expression` разбирает
    ввод как алгебру: `A ^ B` там исключающее ИЛИ. Ошибка была бы
    молчаливой — верный ответ засчитывался бы неверным.
    """

    VALUE = "(not(A) v (B ^ C))"
    VARS = ("A", "B", "C")

    def _spec(self, mode=None):
        from core.answers import LogicSpec

        return (LogicSpec(value=self.VALUE, variables=self.VARS)
                if mode is None
                else LogicSpec(value=self.VALUE, variables=self.VARS,
                               mode=mode))

    def test_any_notation_of_the_same_function_is_accepted(self):
        for text in ["¬A ∨ BC", "!A + B*C", "~A|(B&C)", "not A or B and C"]:
            with self.subTest(text=text):
                self.assertTrue(self._spec().check(text).accepted)

    def test_a_different_function_is_refused(self):
        from core.answers import Reason

        verdict = self._spec().check("A ^ B")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.MISMATCH)

    def test_unreadable_answer_is_reported_as_unparsed(self):
        from core.answers import Reason

        self.assertIs(self._spec().check("A v v").reason, Reason.UNPARSED)
        self.assertIs(self._spec().check("").reason, Reason.EMPTY)

    def test_strict_demands_the_simplified_form(self):
        """
        «Упростите выражение» ломается о мягкую проверку так же, как у
        выражений: неупрощённый эталон ей эквивалентен, а задание не
        решает.
        """
        from core.answers import CheckMode, Reason

        spec = self._spec(CheckMode.STRICT)
        verdict = spec.check("(A v not(A)) ^ (not(A) v (B ^ C))")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.WRONG_FORM)
        self.assertTrue(spec.check("¬A ∨ BC").accepted)

    def test_strict_accepts_another_minimal_form(self):
        # Минимальных записей у функции бывает несколько; отвергать
        # «не ту из правильных» — худший вид строгости.
        from core.answers import CheckMode

        spec = self._spec(CheckMode.STRICT)
        self.assertTrue(spec.check("(B ^ C) v not(A)").accepted)

    def test_examples_are_all_accepted(self):
        """
        Инвариант базового класса: предпросмотр не врёт. В строгом режиме
        он вдобавок обязан не остаться пустым — иначе преподавателю
        показывать нечего.
        """
        from core.answers import CheckMode

        for mode in (CheckMode.SOFT, CheckMode.STRICT):
            spec = self._spec(mode)
            examples = spec.accepted_examples()
            with self.subTest(mode=mode):
                self.assertTrue(examples)
                for text in examples:
                    self.assertTrue(spec.check(text).accepted, text)

    def test_distractors_are_all_wrong(self):
        spec = self._spec()
        wrong = spec.distractors(3)
        self.assertTrue(wrong)
        for text in wrong:
            self.assertFalse(spec.check(text).accepted, text)

    def test_survives_serialisation(self):
        from core.answers import AnswerSpec

        spec = self._spec()
        self.assertEqual(AnswerSpec.from_dict(spec.to_dict()), spec)

    def test_the_answer_does_not_leak_into_the_field(self):
        # `InputField` едет студенту: в подсказке только имена входов,
        # которые и так есть на схеме.
        field = self._spec().input_fields()[0]
        self.assertNotIn("B ^ C", field.hint)
        self.assertIn("A", field.hint)


class CircuitTaskTests(unittest.TestCase):
    """
    Задание целиком: схема в условии, функция в ответе.

    Ровно то, что раньше было непроверяемым. Старый генератор клал ответ
    в текстовый блок «Логическая функция: …» и на этом заканчивался.
    """

    @staticmethod
    def _graph(answer_port: str, statement: str, slot: str):
        return {"nodes": [
            {"id": "m", "type": "model_opvs_circuit", "params": {"inputs": 3}},
            {"id": "b", "type": "image_block",
             "params": {"caption": "Логическая схема"}},
            {"id": "t", "type": "task",
             "params": {"statement": statement, "slots": [slot]}},
        ], "edges": [
            {"from": "m:image", "to": "b:in"},
            {"from": "b:out", "to": "t:blocks"},
            {"from": answer_port, "to": "t:ответ"},
        ]}

    def _run(self, *args):
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec

        return GraphExecutor(GraphSpec.parse(self._graph(*args))).run()

    def test_function_task_is_checkable(self):
        from core.interactive import session_from_task

        task = self._run("m:expr", "Выпишите функцию по схеме.", "ответ:logic")
        self.assertTrue(task.is_checkable)
        self.assertEqual(task.answer_spec.kind, "logic")
        example = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(example).correct)

    def test_the_students_own_notation_is_accepted(self):
        from core.interactive import session_from_task

        task = self._run("m:expr", "Выпишите функцию.", "ответ:logic")
        other = (task.answer_spec.value.replace("^", "&")
                 .replace(" v ", " | ").replace("not", "~"))
        self.assertTrue(session_from_task(task).submit(other).correct,
                        f"{other!r} не принято")

    def test_counting_task_from_the_same_model(self):
        """
        Обратная разводка: та же модель, но спрашивается число наборов.
        Один провод — другое задание, и оба проверяемы.
        """
        from core.interactive import session_from_task

        task = self._run("m:ones", "На скольких наборах функция истинна?",
                         "ответ:number")
        answer = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(answer).correct)
        self.assertTrue(1 <= float(answer) <= 7)

    def test_the_two_tasks_are_different(self):
        first = self._run("m:expr", "Функция?", "ответ:logic")
        second = self._run("m:ones", "Сколько единиц?", "ответ:number")
        self.assertNotEqual(first.answer_spec.kind, second.answer_spec.kind)

    def test_formula_string_cannot_be_wired_into_a_logic_slot(self):
        """
        Строковая запись формулы — оформление; в слот идёт величина.
        Провод обязан отказать при сборке, а не проверить показ вместо
        ответа.
        """
        from core.graph.errors import GraphValidationError
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec

        graph = self._graph("m:formula", "Функция?", "ответ:logic")
        with self.assertRaises(GraphValidationError):
            GraphExecutor(GraphSpec.parse(graph))


if __name__ == "__main__":
    unittest.main()
