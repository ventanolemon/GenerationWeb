"""
Тест как режим показа ответа — этап 6 плана (§2).

Центральное решение здесь принято до кода: **тест это не третий тип
задания, а способ показать ответ**, и порождает варианты та же
типизация, которая даёт проверку. Число можно возмутить, у выражения
сменить знак или степень, из объявленной размерности сделать характерную
ошибку — и всё это знает сама спецификация, потому что знает, что за
величина перед ней.

Отсюда и то, что здесь проверяется:

  * **дистрактор не может оказаться верным.** Инвариант зеркальный
    предпросмотру: там кандидат отбрасывается, если НЕ проходит проверку,
    здесь — если проходит. Тест с двумя правильными ответами заметит
    студент, а не автор;
  * **варианты правдоподобны.** «Яблоко» среди чисел выдаёт верный ответ
    методом исключения, то есть превращает тест в подарок;
  * **порядок устойчив.** Сессия переживает перезапуск сервиса и переезд
    между процессами, варианты собираются заново на той стороне.
    Случайная перетасовка означала бы, что студент между ходами видит
    другой порядок, а он уже запомнил «второй сверху»;
  * **проверяет та же спецификация.** Ответом уезжает текст выбранного
    варианта, и никакого «сравнения по индексу» не заводится — иначе
    правильность зависела бы от порядка показа.
"""

from __future__ import annotations

import unittest

from core.answers import (AnswerSpec, CheckMode, ExpressionSpec, NumberSpec,
                          SlotsSpec, TextSpec, Tolerance, ToleranceKind)
from core.blocks import TextBlock
from core.interactive import Question, SpecSession
from core.widgets import registry


NUMBER = NumberSpec(value=9.8, unit="м/с^2",
                    tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1))
EXPR = ExpressionSpec(value="x**2 - 1", symbols=("x",))
LINEAR = ExpressionSpec(value="2*x + 3", symbols=("x",))


class DistractorIsNeverCorrectTests(unittest.TestCase):
    """
    Главный инвариант этапа. Проверяется прогоном, а не доверием к
    порождению: список неверных вариантов идёт через ту же `check`.
    """

    def test_number(self):
        for wrong in NUMBER.distractors(5):
            with self.subTest(wrong=wrong):
                self.assertFalse(NUMBER.check(wrong).accepted)

    def test_expression(self):
        for spec in (EXPR, LINEAR):
            for wrong in spec.distractors(5):
                with self.subTest(spec=spec.value, wrong=wrong):
                    self.assertFalse(spec.check(wrong).accepted)

    def test_tolerance_is_respected(self):
        """
        Возмущение внутри допуска — верный ответ, а не дистрактор.
        Спецификация с допуском ±50 % обязана отбросить «вдвое больше».
        """
        spec = NumberSpec(value=100.0,
                          tolerance=Tolerance(ToleranceKind.RELATIVE, 0.6))
        for wrong in spec.distractors(5):
            with self.subTest(wrong=wrong):
                self.assertFalse(spec.check(wrong).accepted)

    def test_soft_mode_equivalence_is_respected(self):
        """
        В мягком режиме «1 - x**2» и «-(x**2 - 1)» — одно и то же.
        Дистрактор «сменённый знак» обязан отсеяться там, где ответ
        нулевой: −0 равно 0.
        """
        spec = ExpressionSpec(value="0")
        for wrong in spec.distractors(5):
            with self.subTest(wrong=wrong):
                self.assertFalse(spec.check(wrong).accepted)


class DistractorsArePlausibleTests(unittest.TestCase):

    def test_number_keeps_the_unit(self):
        # Вариант без размерности там, где она объявлена, — тоже ошибка,
        # но именно ТА, ради которой размерность и объявлена.
        wrong = NUMBER.distractors(5)
        self.assertTrue(any("м/с^2" in item for item in wrong))

    def test_number_has_no_float_noise(self):
        """
        «0.9800000000000001» выдаёт машинное происхождение варианта, и
        студент отбрасывает его не думая.
        """
        for item in NUMBER.distractors(5):
            with self.subTest(item=item):
                self.assertNotIn("000000", item)

    def test_expression_distractors_are_expressions(self):
        for wrong in EXPR.distractors(4):
            with self.subTest(wrong=wrong):
                # Должно разбираться той же спецификацией: неразобранный
                # вариант виден невооружённым глазом.
                self.assertIsNot(EXPR.check(wrong).reason.value, "unparsed")

    def test_text_has_no_invented_distractors(self):
        """
        Для строки правдоподобной ошибки из самой строки не построить:
        осмысленные неверные варианты для «Найдите столицу» — другие
        города, и знает их только автор.
        """
        self.assertEqual(TextSpec(value="Москва").distractors(3), [])

    def test_text_takes_declared_wrong_options(self):
        spec = TextSpec(value="Москва",
                        wrong_options=("Казань", "Тверь"))
        self.assertEqual(spec.distractors(3), ["Казань", "Тверь"])

    def test_a_synonym_never_becomes_a_distractor(self):
        """
        Синоним засчитывается, значит вариантом «неверного» быть не может.
        Автор способен перепутать `alt=` и `wrong=`; отсев по собственной
        проверке ловит это до студента.
        """
        spec = TextSpec(value="Москва", alternatives=("Moscow",),
                        wrong_options=("Moscow", "Казань"))
        self.assertEqual(spec.distractors(3), ["Казань"])

    def test_count_is_an_upper_bound(self):
        self.assertLessEqual(len(NUMBER.distractors(2)), 2)


class OptionsTests(unittest.TestCase):

    def test_correct_answer_is_among_the_options(self):
        options = NUMBER.options(4)
        self.assertEqual(sum(1 for o in options if NUMBER.check(o).accepted), 1)

    def test_order_is_stable_across_rebuilds(self):
        """
        Сессия пересобирается в другом процессе — порядок обязан совпасть.
        """
        again = AnswerSpec.from_dict(NUMBER.to_dict())
        self.assertEqual(NUMBER.options(4), again.options(4))

    def test_order_is_not_the_generation_order(self):
        # Иначе верный ответ всегда стоял бы первым.
        first = [NumberSpec(value=v).options(4)[0] for v in (5, 7, 11, 13, 17)]
        correct = [NumberSpec(value=v).accepted_examples()[0]
                   for v in (5, 7, 11, 13, 17)]
        self.assertNotEqual(first, correct)

    def test_no_options_when_a_fair_test_is_impossible(self):
        """
        Тест из одного варианта не тест, и показать его хуже, чем не
        показать: верный ответ виден без всякого решения.
        """
        self.assertEqual(TextSpec(value="Москва").options(4), [])

    def test_no_options_without_an_accepted_example(self):
        self.assertEqual(ExpressionSpec(value=r"\text{непонятно}").options(4), [])


class QuestionShowsTheTestTests(unittest.TestCase):

    def _question(self, spec, count=4):
        return Question(statement=[TextBlock("?")], spec=spec,
                        options_count=count)

    def test_widget_follows_from_the_options(self):
        """
        Выводить это из `options_count` надо в одном месте, иначе одни
        начнут показывать варианты полем ввода, а другие — наоборот.
        """
        self.assertEqual(self._question(NUMBER).widget_name(), "choice_one")

    def test_plain_question_is_a_field(self):
        question = Question(statement=[TextBlock("?")], spec=NUMBER)
        self.assertEqual(question.widget_name(), "text_input")
        self.assertEqual(question.options(), [])

    def test_incompatible_spec_falls_back(self):
        """
        Набор слотов тестом не задаётся. Падать незачем — остаётся
        обычное умолчание реестра.
        """
        grid = self._question(SlotsSpec.from_grid([[1, 2]]))
        self.assertEqual(grid.widget_name(), "grid_fields")
        self.assertEqual(grid.options(), [])

    def test_choice_widget_is_registered(self):
        widget = registry.get("choice_one")
        self.assertIsNotNone(widget)
        self.assertTrue(widget.serves(NUMBER))
        self.assertFalse(widget.serves(SlotsSpec.from_grid([[1]])))

    def test_options_survive_the_session_snapshot(self):
        session = SpecSession([self._question(NUMBER)], max_attempts=1)
        restored = SpecSession([self._question(NUMBER)], max_attempts=1)
        restored.restore(session.state())
        self.assertEqual(restored.questions[0].options(),
                         session.questions[0].options())
        self.assertEqual(restored.questions[0].options_count, 4)


class AnsweringATestTests(unittest.TestCase):
    """
    Ответом уезжает ТЕКСТ варианта, и проверяет его та же спецификация.
    Никакого сравнения по индексу: иначе правильность зависела бы от
    порядка показа, а порядок — вещь презентационная.
    """

    def _session(self, spec):
        return SpecSession(
            [Question(statement=[TextBlock("?")], spec=spec, options_count=4)],
            max_attempts=1)

    def test_picking_the_right_option_is_accepted(self):
        session = self._session(NUMBER)
        options = session.questions[0].options()
        correct = next(o for o in options if NUMBER.check(o).accepted)
        self.assertTrue(session.submit(correct).correct)

    def test_picking_a_wrong_option_is_refused(self):
        session = self._session(NUMBER)
        options = session.questions[0].options()
        wrong = next(o for o in options if not NUMBER.check(o).accepted)
        self.assertFalse(session.submit(wrong).correct)

    def test_typing_the_answer_still_works(self):
        # Тест — режим показа, а не запрет на ввод: та же спецификация
        # принимает и набранное руками.
        session = self._session(NUMBER)
        self.assertTrue(session.submit("9.8 м/с^2").correct)

    def test_strict_mode_reaches_the_options(self):
        spec = ExpressionSpec(value="x**2 - 1", symbols=("x",),
                              mode=CheckMode.STRICT)
        for wrong in spec.distractors(4):
            with self.subTest(wrong=wrong):
                self.assertFalse(spec.check(wrong).accepted)


class GraphSlotTests(unittest.TestCase):
    """`choices=N` в объявлении слота — намерение автора задания."""

    def _run(self, slots):
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec
        return GraphExecutor(GraphSpec.parse({
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 28}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Сколько?", "slots": slots}},
            ],
            "edges": [{"from": "n:out", "to": "t:p"}],
        })).run()

    def test_choices_reach_the_session(self):
        from core.interactive import session_from_task
        task = self._run(["p:number:unit=шт:choices=4"])
        self.assertEqual(task.meta["choices"], 4)
        session = session_from_task(task)
        self.assertEqual(session.questions[0].widget_name(), "choice_one")
        self.assertEqual(len(session.questions[0].options()), 4)

    def test_without_choices_it_is_a_field(self):
        from core.interactive import session_from_task
        task = self._run(["p:number:unit=шт"])
        self.assertNotIn("choices", task.meta)
        self.assertEqual(
            session_from_task(task).questions[0].widget_name(), "text_input")

    def test_one_option_is_refused(self):
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError):
            self._run(["p:number:choices=1"])

    def test_non_numeric_count_is_refused(self):
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError):
            self._run(["p:number:choices=много"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
