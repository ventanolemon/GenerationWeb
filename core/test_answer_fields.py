"""
Поля ввода ответа и ход по полям.

Сквозной путь до экрана упирается в два вопроса, на которые спецификация
обязана отвечать сама:

  * **сколько полей и как их подписать** — иначе набор слотов нарисовать
    нельзя: имена знает только спецификация, а её отвечающему не отдают;
  * **как принять ответ, собранный по полям** — иначе клиенту пришлось бы
    склеивать их в строку «a=1; b=2», и корректность ответа зависела бы от
    того, какие символы в него попали.

Главный тест здесь — не про удобство, а про утечку: `input_fields()` едет
тому, кто отвечает, и ответа в нём быть не должно.
"""

from __future__ import annotations

import json
import unittest

from core.answers import (CheckMode, ExpressionSpec, InputField, NumberSpec,
                          SlotsSpec, TextSpec, Tolerance, ToleranceKind)
from core.interactive import Question, SpecSession
from core.blocks import TextBlock


def _fields_blob(spec) -> str:
    """Ровно то, что уедет клиенту."""
    return json.dumps([f.to_dict() for f in spec.input_fields()],
                      ensure_ascii=False)


def _shown(spec) -> str:
    return " ".join(b.render_plain() for b in spec.display_blocks())


NUMBER = NumberSpec(value=9.81, unit="м/с^2",
                    tolerance=Tolerance(ToleranceKind.SIGNIFICANT, 3))
TEXT = TextSpec(value="Москва", alternatives=("Moscow", "Первопрестольная"))
EXPR = ExpressionSpec(value="x**2 - 1", symbols=("x",))
SLOTS = SlotsSpec(slots=(("v", NUMBER), ("y", EXPR)))


class InputFieldsTests(unittest.TestCase):

    def test_single_field_for_scalar_kinds(self):
        """Число, строка и выражение отличаются виджетом, а не числом полей."""
        for spec in (NUMBER, TEXT, EXPR):
            with self.subTest(kind=spec.kind):
                fields = spec.input_fields()
                self.assertEqual(len(fields), 1)
                self.assertEqual(fields[0].kind, spec.kind)
                self.assertEqual(fields[0].name, "")

    def test_one_field_per_slot(self):
        fields = SLOTS.input_fields()
        self.assertEqual([f.name for f in fields], ["v", "y"])
        self.assertEqual([f.kind for f in fields], ["number", "expression"])

    def test_slot_inherits_the_hint_of_its_own_spec(self):
        """Внутри набора «м/с^2» работает так же, как поодиночке."""
        by_name = {f.name: f for f in SLOTS.input_fields()}
        self.assertEqual(by_name["v"].hint, NUMBER.input_fields()[0].hint)
        self.assertIn("x", by_name["y"].hint)

    def test_unit_is_a_hint(self):
        self.assertEqual(NUMBER.input_fields()[0].hint, "м/с^2")

    def test_expression_hints_its_variables(self):
        self.assertEqual(EXPR.input_fields()[0].hint, "переменные: x")

    def test_expression_without_symbols_has_no_hint(self):
        self.assertEqual(ExpressionSpec(value="42").input_fields()[0].hint, "")

    def test_empty_parts_are_not_serialized(self):
        # Пустые поля не должны занимать место в каждом ответе сессии.
        self.assertEqual(InputField(kind="text").to_dict(), {"kind": "text"})


class NoAnswerLeaksTests(unittest.TestCase):
    """
    Описание полей едет ОТВЕЧАЮЩЕМУ. Спецификация — нет.

    Проверка тупая нарочно: сериализуем ровно то, что уйдёт клиенту, и
    ищем в этом ответ. Если однажды кто-то добавит в поле «подсказку»
    вида «примерно 9.8», тест упадёт — и это правильное место, чтобы
    об этом узнать.
    """

    def test_number_does_not_leak(self):
        blob = _fields_blob(NUMBER)
        self.assertNotIn("9.81", blob)
        self.assertNotIn(_shown(NUMBER), blob)

    def test_text_does_not_leak(self):
        blob = _fields_blob(TEXT)
        self.assertNotIn("Москва", blob)
        for alternative in TEXT.alternatives:
            self.assertNotIn(alternative, blob)

    def test_expression_does_not_leak(self):
        blob = _fields_blob(EXPR)
        self.assertNotIn(EXPR.value, blob)
        self.assertNotIn(_shown(EXPR), blob)

    def test_slots_do_not_leak(self):
        blob = _fields_blob(SLOTS)
        for _, inner in SLOTS.slots:
            self.assertNotIn(_shown(inner), blob)
        self.assertNotIn("9.81", blob)

    def test_tolerance_does_not_leak(self):
        # Допуск — тоже подсказка к ответу: «±0.5» сужает перебор.
        spec = NumberSpec(value=100.0,
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.5))
        self.assertNotIn("0.5", _fields_blob(spec))


class SubmitValuesTests(unittest.TestCase):
    """Ход по полям — путь виджета с раздельными полями."""

    def _session(self, spec):
        return SpecSession(
            [Question(statement=[TextBlock("?")], spec=spec)],
            max_attempts=1)

    def test_slots_are_checked_by_name(self):
        session = self._session(SLOTS)
        # Размерность объявлена, значит обязательна: «9.81» без единиц
        # не проходит, и подсказка у поля существует ровно поэтому.
        result = session.submit_values({"v": "9.81 м/с^2", "y": "x^2-1"})
        self.assertTrue(result.correct)

    def test_declared_unit_is_required(self):
        session = self._session(SLOTS)
        result = session.submit_values({"v": "9.81", "y": "x^2-1"})
        self.assertFalse(result.correct)

    def test_wrong_slot_is_named(self):
        session = self._session(SLOTS)
        result = session.submit_values({"v": "1 м/с^2", "y": "x^2-1"})
        self.assertFalse(result.correct)
        self.assertIn("v", " ".join(b.render_plain() for b in result.feedback))

    def test_single_field_spec_accepts_a_dict_too(self):
        """
        Клиент не обязан знать заранее, сколько полей у вопроса: он шлёт
        то, что собрал с формы.
        """
        session = self._session(NUMBER)
        self.assertTrue(session.submit_values({"": "9.81 м/с^2"}).correct)

    def test_separator_inside_a_value_survives(self):
        """
        Ради чего этот путь и существует.

        Склеенная строка разбирается по «;» и «=», поэтому значение с
        этими символами меняло бы разбор — корректность ответа зависела бы
        от того, какие символы в него попали. По полям такого не бывает.
        """
        spec = SlotsSpec(slots=(
            ("a", TextSpec(value="раз; два", max_edits=0)),
            ("b", TextSpec(value="три", max_edits=0)),
        ))
        session = self._session(spec)
        self.assertTrue(
            session.submit_values({"a": "раз; два", "b": "три"}).correct)

        # Тот же ответ, склеенный в строку, не проходит — не потому, что
        # он неверный, а потому, что точка с запятой внутри значения
        # разобралась как разделитель.
        joined = self._session(spec)
        self.assertFalse(joined.submit("a=раз; два; b=три").correct)

    def test_finished_session_says_so(self):
        session = self._session(NUMBER)
        session.submit_values({"": "9.81 м/с^2"})
        result = session.submit_values({"": "что угодно"})
        self.assertFalse(result.correct)
        self.assertIsNone(result.next_prompt)

    def test_mode_of_the_session_reaches_the_slots(self):
        spec = SlotsSpec(slots=(("y", ExpressionSpec(value="x**2 - 1",
                                                     symbols=("x",))),))
        strict = SpecSession(
            [Question(statement=[TextBlock("?")], spec=spec)],
            mode=CheckMode.STRICT, max_attempts=1)
        self.assertFalse(strict.submit_values({"y": "(x-1)*(x+1)"}).correct)


if __name__ == "__main__":
    unittest.main(verbosity=2)
