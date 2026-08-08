"""
Тесты общей интерактивной сессии и реестра виджетов (этап 2).

Главное, что здесь закрепляется:
  * готовое статическое задание становится интерактивным обогащением
    ответа, а не новым подклассом InteractiveTask;
  * снимок сессии несёт сами вопросы, поэтому переезд между процессами
    возвращает студенту ТО ЖЕ условие, а не свежесгенерированное;
  * выбор формата — из совместимых, а не из общего меню.
"""

import unittest

from core.answers import (
    CheckMode, ExpressionSpec, NumberSpec, SlotsSpec, TextSpec, Tolerance,
    ToleranceKind,
)
from core.blocks import (
    CodeBlock, FormulaBlock, TableBlock, TextBlock, block_from_dict,
    blocks_from_dicts,
)
from core.interactive import (
    Outcome, Question, SpecSession, question_from_task, session_from_task,
    session_from_tasks,
)
from core.task import StaticTask
from core.widgets import (
    Widget, WidgetRegistry, resolve_widget, widgets_for,
)


def number_question(value=2.0, **kw):
    return Question(statement=[TextBlock("Сколько будет 1+1?")],
                    spec=NumberSpec(value=value, **kw))


# ======================================================================
#  Обратный разбор блоков
# ======================================================================

class BlockRoundTripTests(unittest.TestCase):
    """
    Без этого снимок сессии не может нести условие, а значит сессия не
    переживает переезд между процессами.
    """

    SAMPLES = (
        TextBlock("условие"),
        FormulaBlock("x^2 - 1"),
        CodeBlock("print(1)", "python"),
        TableBlock([["1", "2"], ["3", "4"]], ["a", "b"]),
    )

    def test_round_trip_preserves_dict(self):
        for block in self.SAMPLES:
            with self.subTest(kind=type(block).__name__):
                restored = block_from_dict(block.to_dict())
                self.assertEqual(restored.to_dict(), block.to_dict())

    def test_round_trip_preserves_type(self):
        for block in self.SAMPLES:
            restored = block_from_dict(block.to_dict())
            self.assertIsInstance(restored, type(block))

    def test_list_helper(self):
        blocks = blocks_from_dicts([b.to_dict() for b in self.SAMPLES])
        self.assertEqual(len(blocks), len(self.SAMPLES))

    def test_empty_list(self):
        self.assertEqual(blocks_from_dicts(None), [])

    def test_unknown_type_raises(self):
        # Заглушка вместо блока выглядит как испорченное задание, и
        # причину пришлось бы искать в отрендеренном виде.
        with self.assertRaises(ValueError):
            block_from_dict({"type": "мимокрокодил"})

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            block_from_dict("текст")


# ======================================================================
#  Реестр виджетов (§3)
# ======================================================================

class WidgetRegistryTests(unittest.TestCase):

    def test_number_gets_plain_input(self):
        names = [w.name for w in widgets_for(NumberSpec(value=1.0))]
        self.assertIn("text_input", names)

    def test_expression_also_gets_formula_palette(self):
        names = [w.name for w in widgets_for(ExpressionSpec(value="x"))]
        self.assertIn("text_input", names)
        self.assertIn("formula_input", names)

    def test_number_does_not_get_formula_palette(self):
        # Выбор формата — из совместимых, а не общее меню.
        names = [w.name for w in widgets_for(NumberSpec(value=1.0))]
        self.assertNotIn("formula_input", names)

    def test_slots_get_slot_widgets_only(self):
        spec = SlotsSpec(slots=(("a", NumberSpec(value=1.0)),))
        names = [w.name for w in widgets_for(spec)]
        # Все три обслуживают набор слотов; `grid_fields` появился вместе
        # с формой раскладки и совместим по тому же признаку — вид ответа
        # у сетки и у набора полей один.
        self.assertEqual(set(names),
                         {"slot_fields", "grid_fields", "slot_inline"})

    def test_shape_decides_between_compatible_slot_widgets(self):
        """
        Совместимость по виду ответа не различает набор полей и сетку:
        различает ФОРМА, и спрашивают о ней саму спецификацию.
        """
        plain = SlotsSpec(slots=(("a", NumberSpec(value=1.0)),))
        grid = SlotsSpec.from_grid([[1, 2]])
        self.assertEqual(resolve_widget(plain).name, "slot_fields")
        self.assertEqual(resolve_widget(grid).name, "grid_fields")

    def test_default_is_first_compatible(self):
        self.assertEqual(resolve_widget(ExpressionSpec(value="x")).name,
                         "text_input")

    def test_named_widget_is_honoured(self):
        chosen = resolve_widget(ExpressionSpec(value="x"), "formula_input")
        self.assertEqual(chosen.name, "formula_input")

    def test_incompatible_name_raises(self):
        # Молчаливая подмена спрятала бы ошибку настройки до момента,
        # когда студент увидит не тот способ ввода.
        with self.assertRaises(ValueError):
            resolve_widget(NumberSpec(value=1.0), "slot_fields")

    def test_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            resolve_widget(NumberSpec(value=1.0), "телепатия")

    def test_duplicate_registration_refused(self):
        # Имя виджета лежит в снимках сессий; подмена реализации под тем
        # же именем меняла бы поведение уже выданных заданий.
        registry = WidgetRegistry()
        widget = Widget(name="w", title="W", kinds=frozenset({"number"}))
        registry.register(widget)
        with self.assertRaises(ValueError):
            registry.register(widget)

    def test_new_widget_needs_no_core_change(self):
        registry = WidgetRegistry()
        registry.register(Widget(name="dial", title="Крутилка",
                                 kinds=frozenset({"number"})))
        self.assertEqual(
            [w.name for w in registry.for_spec(NumberSpec(value=1.0))], ["dial"])


# ======================================================================
#  Обогащение задания (§1)
# ======================================================================

class StaticTaskEnrichmentTests(unittest.TestCase):

    def plain(self):
        return StaticTask(statement=[TextBlock("условие")],
                          answer=[TextBlock("2")])

    def enriched(self):
        return StaticTask(statement=[TextBlock("условие")],
                          answer=[TextBlock("2")],
                          answer_spec=NumberSpec(value=2.0))

    def test_plain_task_is_not_checkable(self):
        self.assertFalse(self.plain().is_checkable)

    def test_enriched_task_is_checkable(self):
        self.assertTrue(self.enriched().is_checkable)

    def test_rendered_answer_is_untouched(self):
        # Спецификация кладётся РЯДОМ: старый показ обязан работать без
        # единой правки, иначе обогащение превращается в переписывание.
        task = self.enriched()
        self.assertEqual([b.render_plain() for b in task.answer], ["2"])

    def test_serialization_exposes_spec_and_widgets(self):
        data = self.enriched().to_dict()
        self.assertTrue(data["is_checkable"])
        self.assertEqual(data["answer_spec"]["kind"], "number")
        self.assertIn("text_input", [w["name"] for w in data["widgets"]])

    def test_serialization_of_plain_task_unchanged(self):
        data = self.plain().to_dict()
        self.assertFalse(data["is_checkable"])
        self.assertNotIn("answer_spec", data)
        self.assertNotIn("widgets", data)


# ======================================================================
#  Сборка сессии из заданий
# ======================================================================

class SessionAssemblyTests(unittest.TestCase):

    def test_plain_task_yields_no_session(self):
        task = StaticTask(statement=[TextBlock("у")], answer=[TextBlock("о")])
        self.assertIsNone(session_from_task(task))

    def test_enriched_task_yields_session(self):
        task = StaticTask(statement=[TextBlock("у")], answer=[TextBlock("2")],
                          answer_spec=NumberSpec(value=2.0))
        self.assertIsInstance(session_from_task(task), SpecSession)

    def test_mixed_batch_keeps_only_checkable(self):
        tasks = [
            StaticTask(statement=[TextBlock("a")], answer=[], answer_spec=None),
            StaticTask(statement=[TextBlock("b")], answer=[],
                       answer_spec=NumberSpec(value=1.0)),
        ]
        session = session_from_tasks(tasks)
        self.assertEqual(len(session.questions), 1)

    def test_batch_without_specs_yields_none(self):
        tasks = [StaticTask(statement=[TextBlock("a")], answer=[])]
        self.assertIsNone(session_from_tasks(tasks))

    def test_widget_preference_read_from_meta(self):
        task = StaticTask(
            statement=[TextBlock("у")], answer=[],
            answer_spec=ExpressionSpec(value="x"),
            meta={"widget": "formula_input"})
        self.assertEqual(question_from_task(task).widget_name(),
                         "formula_input")


# ======================================================================
#  Цикл «спроси → проверь → покажи»
# ======================================================================

class SessionLoopTests(unittest.TestCase):

    def test_initial_prompt_is_the_statement(self):
        session = SpecSession([number_question()])
        self.assertEqual([b.render_plain() for b in session.initial_prompt()],
                         ["Сколько будет 1+1?"])

    def test_correct_answer_finishes_single_question_session(self):
        session = SpecSession([number_question()])
        result = session.submit("2")
        self.assertTrue(result.correct)
        self.assertIsNone(result.next_prompt)
        self.assertTrue(session.is_finished())

    def test_wrong_answer_also_advances_when_one_attempt(self):
        session = SpecSession([number_question()])
        result = session.submit("5")
        self.assertFalse(result.correct)
        self.assertTrue(session.is_finished())

    def test_answer_is_revealed_after_failure(self):
        session = SpecSession([number_question()])
        shown = " ".join(b.render_plain() for b in session.submit("5").feedback)
        self.assertIn("Правильный ответ:", shown)
        self.assertIn("2", shown)

    def test_answer_not_revealed_when_disabled(self):
        session = SpecSession([number_question()], reveal_answer=False)
        shown = " ".join(b.render_plain() for b in session.submit("5").feedback)
        self.assertNotIn("Правильный ответ:", shown)

    def test_sequence_advances_to_next_statement(self):
        session = SpecSession([
            Question([TextBlock("первый")], NumberSpec(value=1.0)),
            Question([TextBlock("второй")], NumberSpec(value=2.0)),
        ])
        result = session.submit("1")
        self.assertEqual([b.render_plain() for b in result.next_prompt],
                         ["второй"])
        self.assertFalse(session.is_finished())

    def test_submit_after_finish_is_safe(self):
        session = SpecSession([number_question()])
        session.submit("2")
        result = session.submit("2")
        self.assertFalse(result.correct)
        self.assertIsNone(result.next_prompt)

    def test_empty_session_is_finished_immediately(self):
        session = SpecSession([])
        self.assertTrue(session.is_finished())
        self.assertIn("Вопросов нет",
                      session.initial_prompt()[0].render_plain())

    def test_mode_is_passed_to_the_spec(self):
        question = Question([TextBlock("у")],
                            ExpressionSpec(value="x**2-1", symbols=("x",)))
        soft = SpecSession([question], mode=CheckMode.SOFT)
        strict = SpecSession([question], mode=CheckMode.STRICT)
        self.assertTrue(soft.submit("(x-1)*(x+1)").correct)
        self.assertFalse(strict.submit("(x-1)*(x+1)").correct)

    def test_slot_feedback_names_the_wrong_field(self):
        spec = SlotsSpec(slots=(("v", NumberSpec(value=10.0)),
                                ("t", NumberSpec(value=2.0))))
        session = SpecSession([Question([TextBlock("у")], spec)])
        shown = " ".join(b.render_plain()
                         for b in session.submit("v=10; t=9").feedback)
        self.assertIn("t", shown)


class RetryTests(unittest.TestCase):

    def test_retry_repeats_the_same_statement(self):
        session = SpecSession([number_question()], max_attempts=2)
        result = session.submit("5")
        self.assertFalse(result.correct)
        self.assertEqual([b.render_plain() for b in result.next_prompt],
                         ["Сколько будет 1+1?"])
        self.assertFalse(session.is_finished())

    def test_second_attempt_can_succeed(self):
        session = SpecSession([number_question()], max_attempts=2)
        session.submit("5")
        self.assertTrue(session.submit("2").correct)
        self.assertTrue(session.is_finished())

    def test_attempts_left_are_reported(self):
        session = SpecSession([number_question()], max_attempts=3)
        shown = " ".join(b.render_plain() for b in session.submit("5").feedback)
        self.assertIn("Осталось попыток: 2", shown)

    def test_exhausted_attempts_close_the_question(self):
        session = SpecSession([number_question()], max_attempts=2)
        session.submit("5")
        session.submit("7")
        self.assertTrue(session.is_finished())

    def test_one_outcome_per_question_not_per_attempt(self):
        # Иначе одна попытка из нескольких попала бы в статистику как
        # отдельный результат, и «8 из 10» стало бы неинтерпретируемым.
        session = SpecSession([number_question()], max_attempts=3)
        session.submit("5")
        session.submit("6")
        session.submit("2")
        self.assertEqual(len(session.outcomes), 1)
        self.assertTrue(session.outcomes[0].accepted)
        self.assertEqual(session.outcomes[0].attempts, 3)


class OutcomeTests(unittest.TestCase):

    def test_outcome_records_mode_and_reason(self):
        session = SpecSession([number_question()], mode=CheckMode.STRICT)
        session.submit("2")
        outcome = session.outcomes[0]
        self.assertEqual(outcome.mode, "strict")
        self.assertEqual(outcome.reason, "exact")

    def test_score_counts_only_closed_questions(self):
        session = SpecSession([
            Question([TextBlock("1")], NumberSpec(value=1.0)),
            Question([TextBlock("2")], NumberSpec(value=2.0)),
        ])
        session.submit("1")
        self.assertEqual(session.score, (1, 2))

    def test_outcome_round_trip(self):
        outcome = Outcome(index=0, accepted=True, attempts=2,
                          mode="soft", reason="tolerance")
        self.assertEqual(Outcome.from_dict(outcome.to_dict()), outcome)


# ======================================================================
#  Снимок и восстановление
# ======================================================================

class SnapshotTests(unittest.TestCase):
    """
    Ключевое свойство: снимок несёт САМИ ВОПРОСЫ.

    WordsSession мог снимать только прогресс — словарь лежит в БД и
    пересобирается детерминированно. Здесь вопрос породил генератор со
    случайными параметрами, и восстановление одного прогресса показало бы
    студенту не то задание, на которое он отвечал.
    """

    def session(self):
        return SpecSession([
            Question([TextBlock("первый")], NumberSpec(value=1.0)),
            Question([TextBlock("второй")],
                     TextSpec(value="ток", alternatives=("current",))),
        ], mode=CheckMode.SOFT, max_attempts=2)

    def test_snapshot_is_json_serializable(self):
        import json
        json.dumps(self.session().state())

    def test_restore_returns_the_same_question(self):
        original = self.session()
        original.submit("1")
        snapshot = original.state()

        # Свежая сессия с ДРУГИМИ вопросами — как если бы генератор
        # пересобрал задание в другом процессе.
        revived = SpecSession([Question([TextBlock("совсем другое")],
                                        NumberSpec(value=99.0))])
        revived.restore(snapshot)

        self.assertEqual([b.render_plain() for b in revived.initial_prompt()],
                         ["второй"])

    def test_restore_preserves_progress(self):
        original = self.session()
        original.submit("1")
        revived = SpecSession([])
        revived.restore(original.state())
        self.assertEqual(revived.score, (1, 2))
        self.assertEqual(len(revived.outcomes), 1)

    def test_restore_preserves_settings(self):
        original = SpecSession([number_question()], mode=CheckMode.STRICT,
                               max_attempts=3, reveal_answer=False)
        revived = SpecSession([])
        revived.restore(original.state())
        shown = " ".join(b.render_plain()
                         for b in revived.submit("5").feedback)
        self.assertIn("Осталось попыток: 2", shown)
        self.assertNotIn("Правильный ответ", shown)

    def test_restore_mid_question_keeps_attempt_count(self):
        original = SpecSession([number_question()], max_attempts=2)
        original.submit("5")                 # одна попытка израсходована
        revived = SpecSession([])
        revived.restore(original.state())
        revived.submit("7")                  # вторая — вопрос закрывается
        self.assertTrue(revived.is_finished())

    def test_spec_survives_the_round_trip(self):
        original = SpecSession([Question(
            [TextBlock("у")],
            ExpressionSpec(value="x+1", symbols=("x",),
                           reject_equivalent_to=("(x**2-1)/(x-1)",)))])
        revived = SpecSession([])
        revived.restore(original.state())
        # Запрет на повтор условия обязан пережить переезд: иначе после
        # перезапуска процесса задание начнёт засчитывать нерешённое.
        self.assertFalse(revived.submit("(x**2-1)/(x-1)").correct)

    def test_snapshot_of_finished_session(self):
        original = SpecSession([number_question()])
        original.submit("2")
        revived = SpecSession([])
        revived.restore(original.state())
        self.assertTrue(revived.is_finished())


# ======================================================================
#  Приёмка этапа
# ======================================================================

class NoSubclassNeededTests(unittest.TestCase):
    """
    Приёмочный признак этапа 2: чтобы задание стало интерактивным, не
    нужен новый подкласс InteractiveTask с собственным циклом.
    """

    def test_static_task_becomes_interactive_without_new_class(self):
        task = StaticTask(
            statement=[TextBlock("Ускорение свободного падения?")],
            answer=[TextBlock("9.8 м/с^2")],
            answer_spec=NumberSpec(
                value=9.8, unit="м/с^2",
                tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1)))

        session = session_from_task(task)

        self.assertIs(type(session), SpecSession)
        self.assertEqual([b.render_plain() for b in session.initial_prompt()],
                         ["Ускорение свободного падения?"])
        self.assertTrue(session.submit("9.85 м/с^2").correct)

    def test_the_only_generator_change_is_one_field(self):
        # Задание без спецификации и с ней отличаются ровно одним полем,
        # а показ ответа у них совпадает.
        common = dict(statement=[TextBlock("у")], answer=[TextBlock("2")])
        plain = StaticTask(**common)
        checkable = StaticTask(**common, answer_spec=NumberSpec(value=2.0))
        self.assertEqual(plain.to_dict()["statement"],
                         checkable.to_dict()["statement"])
        self.assertEqual(plain.to_dict()["answer"],
                         checkable.to_dict()["answer"])


if __name__ == "__main__":
    unittest.main()
