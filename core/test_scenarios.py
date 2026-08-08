"""
Сценарий прохождения и модель попытки (этап 3).

Закрепляется то, что нельзя восстановить задним числом:
  * четыре режима — четыре РАЗНЫХ контракта о записи попытки, а не четыре
    набора настроек;
  * замок принадлежит выдаче, и слой ниже его не обходит;
  * адаптация в запрещающем режиме отвергается громко, а не приводится
    к False молча;
  * в попытке лежит и режим прохождения, и режим проверки, и пометка
    адаптивности — иначе статистика начнёт смешивать разное.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core.answers import CheckMode, NumberSpec  # noqa: E402
from core.attempts import attempt_uuid, attempts_from_session  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.interactive import Question, SpecSession  # noqa: E402
from core.scenarios import (  # noqa: E402
    ADAPTIVE, CHECK_MODE, CONTRACTS, IMPLEMENTED_MODES, MAX_ATTEMPTS,
    PARAMETERS, REVEAL_ANSWER, Layer, Scenario, ScenarioError, SessionMode,
    default_scenario,
)


def a_session(scenario=None, count=2):
    questions = [
        Question([TextBlock(f"вопрос {i}")], NumberSpec(value=float(i)))
        for i in range(count)
    ]
    return SpecSession(questions, scenario=scenario)


# ======================================================================
#  Контракты режимов
# ======================================================================

class RecordingContractTests(unittest.TestCase):
    """
    Отличие «тренировки без статистики» от «тренировки со статистикой» —
    не значение параметра, а то, появится ли строка вообще.
    """

    def test_every_mode_has_a_contract(self):
        for mode in SessionMode:
            self.assertIn(mode, CONTRACTS)

    def test_free_practice_records_nothing(self):
        contract = CONTRACTS[SessionMode.PRACTICE_FREE]
        self.assertFalse(contract.records_attempts)
        self.assertFalse(contract.counts_toward_stats)

    def test_practice_records_and_counts(self):
        contract = CONTRACTS[SessionMode.PRACTICE]
        self.assertTrue(contract.records_attempts)
        self.assertTrue(contract.counts_toward_stats)

    def test_homework_and_exam_forbid_adaptation(self):
        # Адаптация ломает сравнимость: «8 из 10» у двух студентов с
        # разными последовательностями значит разное.
        for mode in (SessionMode.HOMEWORK, SessionMode.EXAM):
            self.assertFalse(CONTRACTS[mode].adaptation_allowed)

    def test_exam_defaults_are_strict(self):
        exam = Scenario.for_mode(SessionMode.EXAM)
        self.assertEqual(exam.max_attempts, 1)
        self.assertIs(exam.check_mode, CheckMode.STRICT)
        self.assertFalse(exam.reveal_answer)

    def test_only_two_modes_are_open_today(self):
        # Модель описывает четыре, достижимы два: ДЗ и зачёту нужна
        # дисциплина выдачи, которой ещё нет.
        self.assertEqual(
            IMPLEMENTED_MODES,
            frozenset({SessionMode.PRACTICE_FREE, SessionMode.PRACTICE}))

    def test_every_mode_defines_every_parameter(self):
        for mode in SessionMode:
            for name in PARAMETERS:
                with self.subTest(mode=mode, param=name):
                    self.assertIn(name, CONTRACTS[mode].defaults)


# ======================================================================
#  Каскад слоёв
# ======================================================================

class CascadeTests(unittest.TestCase):

    def test_defaults_sit_on_the_task_layer(self):
        scenario = Scenario.for_mode(SessionMode.PRACTICE)
        self.assertIs(scenario.set_by(MAX_ATTEMPTS), Layer.TASK)
        self.assertFalse(scenario.is_locked(MAX_ATTEMPTS))

    def test_assignment_overrides_task(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {MAX_ATTEMPTS: 1}))
        self.assertEqual(scenario.max_attempts, 1)
        self.assertIs(scenario.set_by(MAX_ATTEMPTS), Layer.ASSIGNMENT)

    def test_student_overrides_unlocked(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.STUDENT, {MAX_ATTEMPTS: 5}))
        self.assertEqual(scenario.max_attempts, 5)

    def test_student_cannot_override_locked(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {MAX_ATTEMPTS: 1},
                                lock=[MAX_ATTEMPTS]))
        with self.assertRaises(ScenarioError):
            scenario.with_layer(Layer.STUDENT, {MAX_ATTEMPTS: 5})

    def test_lock_without_value_still_locks(self):
        # Преподаватель может запереть умолчание, не меняя его.
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, lock=[CHECK_MODE]))
        self.assertTrue(scenario.is_locked(CHECK_MODE))
        with self.assertRaises(ScenarioError):
            scenario.with_layer(Layer.STUDENT, {CHECK_MODE: CheckMode.STRICT})

    def test_only_assignment_may_lock(self):
        # «Набор параметров один, замок — свойство выдачи» (§4). Автор
        # задания запирать не может: иначе он определял бы условия чужого
        # занятия.
        base = Scenario.for_mode(SessionMode.PRACTICE)
        for layer in (Layer.TASK, Layer.STUDENT):
            with self.subTest(layer=layer):
                with self.assertRaises(ScenarioError):
                    base.with_layer(layer, {MAX_ATTEMPTS: 2},
                                    lock=[MAX_ATTEMPTS])

    def test_unknown_parameter_is_refused(self):
        # Опечатка в имени иначе молча ничего не сделает, и искать её
        # будут в поведении.
        with self.assertRaises(ScenarioError):
            Scenario.for_mode(SessionMode.PRACTICE).with_layer(
                Layer.ASSIGNMENT, {"max_atempts": 3})

    def test_open_to_student_lists_unlocked(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, lock=[MAX_ATTEMPTS,
                                                        CHECK_MODE]))
        open_now = scenario.open_to_student()
        self.assertNotIn(MAX_ATTEMPTS, open_now)
        self.assertIn(REVEAL_ANSWER, open_now)

    def test_assignment_may_relock_its_own_value(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {MAX_ATTEMPTS: 2},
                                lock=[MAX_ATTEMPTS])
                    .with_layer(Layer.ASSIGNMENT, {MAX_ATTEMPTS: 4},
                                lock=[MAX_ATTEMPTS]))
        self.assertEqual(scenario.max_attempts, 4)


class AdaptationTests(unittest.TestCase):

    def test_adaptation_allowed_in_practice(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {ADAPTIVE: True}))
        self.assertTrue(scenario.adaptive)

    def test_adaptation_refused_loudly_in_exam(self):
        # Тихое приведение к False дало бы преподавателю уверенность, что
        # адаптация включена, — а она нет.
        with self.assertRaises(ScenarioError):
            Scenario.for_mode(SessionMode.EXAM).with_layer(
                Layer.ASSIGNMENT, {ADAPTIVE: True})

    def test_adaptation_refused_in_homework(self):
        with self.assertRaises(ScenarioError):
            Scenario.for_mode(SessionMode.HOMEWORK).with_layer(
                Layer.ASSIGNMENT, {ADAPTIVE: True})

    def test_adaptation_off_by_default_everywhere(self):
        for mode in SessionMode:
            with self.subTest(mode=mode):
                self.assertFalse(Scenario.for_mode(mode).adaptive)


class ScenarioSerializationTests(unittest.TestCase):

    def scenario(self):
        return (Scenario.for_mode(SessionMode.PRACTICE)
                .with_layer(Layer.ASSIGNMENT,
                            {MAX_ATTEMPTS: 2, CHECK_MODE: CheckMode.STRICT},
                            lock=[CHECK_MODE]))

    def test_round_trip(self):
        original = self.scenario()
        restored = Scenario.from_dict(original.to_dict())
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_round_trip_preserves_lock(self):
        restored = Scenario.from_dict(self.scenario().to_dict())
        self.assertTrue(restored.is_locked(CHECK_MODE))
        with self.assertRaises(ScenarioError):
            restored.with_layer(Layer.STUDENT, {CHECK_MODE: CheckMode.SOFT})

    def test_check_mode_survives_as_enum(self):
        restored = Scenario.from_dict(self.scenario().to_dict())
        self.assertIs(restored.check_mode, CheckMode.STRICT)

    def test_json_serializable(self):
        import json
        json.dumps(self.scenario().to_dict())

    def test_default_scenario_is_free_practice(self):
        self.assertIs(default_scenario().mode, SessionMode.PRACTICE_FREE)


# ======================================================================
#  Сценарий как источник параметров сессии
# ======================================================================

class ScenarioDrivesSessionTests(unittest.TestCase):

    def test_session_takes_attempts_from_scenario(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {MAX_ATTEMPTS: 2}))
        session = a_session(scenario, count=1)
        self.assertFalse(session.submit("999").correct)
        self.assertFalse(session.is_finished(), "должна остаться вторая попытка")

    def test_session_takes_check_mode_from_scenario(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT,
                                {CHECK_MODE: CheckMode.STRICT}))
        session = a_session(scenario, count=1)
        session.submit("0")
        self.assertEqual(session.outcomes[0].mode, "strict")

    def test_session_takes_reveal_from_scenario(self):
        scenario = Scenario.for_mode(SessionMode.EXAM)
        session = SpecSession([Question([TextBlock("у")],
                                        NumberSpec(value=1.0))],
                              scenario=scenario)
        shown = " ".join(b.render_plain() for b in session.submit("9").feedback)
        self.assertNotIn("Правильный ответ", shown)

    def test_scenario_survives_the_snapshot(self):
        # Иначе после переезда сессия «без статистики» начнёт писать
        # попытки: контракт был бы утрачен вместе со сценарием.
        original = a_session(Scenario.for_mode(SessionMode.PRACTICE_FREE))
        revived = SpecSession([])
        revived.restore(original.state())
        self.assertIs(revived.scenario.mode, SessionMode.PRACTICE_FREE)

    def test_session_without_scenario_has_none(self):
        self.assertIsNone(a_session().scenario)


# ======================================================================
#  Попытка
# ======================================================================

class AttemptBuildingTests(unittest.TestCase):

    def finished(self, mode):
        scenario = Scenario.for_mode(mode)
        session = a_session(scenario)
        session.submit("0")
        session.submit("1")
        return session, scenario

    def build(self, mode):
        session, scenario = self.finished(mode)
        return attempts_from_session(
            session, scenario, session_id="sid", user_id="ivanov",
            partition_id=42)

    def test_free_practice_produces_nothing(self):
        # Пустой список — это исполненный контракт, а не «нечего писать».
        self.assertEqual(self.build(SessionMode.PRACTICE_FREE), [])

    def test_practice_produces_one_record_per_question(self):
        records = self.build(SessionMode.PRACTICE)
        self.assertEqual(len(records), 2)

    def test_record_carries_session_mode(self):
        self.assertEqual(self.build(SessionMode.PRACTICE)[0].session_mode,
                         "practice")

    def test_record_carries_check_mode(self):
        self.assertEqual(self.build(SessionMode.PRACTICE)[0].check_mode, "soft")

    def test_check_mode_comes_from_the_verdict_not_the_scenario(self):
        # Если ход проверяли перекрытым режимом, в попытке обязано быть
        # то, чем на самом деле проверяли.
        scenario = Scenario.for_mode(SessionMode.PRACTICE)
        session = a_session(scenario, count=1)
        session._mode = CheckMode.STRICT      # как перекрытие на ход
        session.submit("0")
        record = attempts_from_session(
            session, scenario, session_id="sid", user_id="u",
            partition_id=1)[0]
        self.assertEqual(record.check_mode, "strict")

    def test_record_carries_correctness(self):
        records = self.build(SessionMode.PRACTICE)
        self.assertTrue(records[0].correct)
        self.assertTrue(records[1].correct)

    def test_record_carries_counts_flag(self):
        self.assertTrue(self.build(SessionMode.PRACTICE)[0].counts_toward_stats)

    def test_only_closed_questions_are_recorded(self):
        scenario = Scenario.for_mode(SessionMode.PRACTICE)
        session = a_session(scenario)
        session.submit("0")               # закрыт только первый
        records = attempts_from_session(
            session, scenario, session_id="sid", user_id="u", partition_id=1)
        self.assertEqual(len(records), 1)

    def test_uuid_is_deterministic(self):
        self.assertEqual(attempt_uuid("sid", 0), attempt_uuid("sid", 0))
        self.assertNotEqual(attempt_uuid("sid", 0), attempt_uuid("sid", 1))
        self.assertNotEqual(attempt_uuid("a", 0), attempt_uuid("b", 0))


if __name__ == "__main__":
    unittest.main()
