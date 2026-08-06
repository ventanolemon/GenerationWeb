"""
Обогащение физики проверяемым ответом — пилот из §1 плана.

Проверяем не «спецификация появилась», а то, ради чего пилот и делался:

  * **конфиги в БД не переписаны.** Спецификация строится из того, что в
    них уже есть. Если это перестанет быть правдой, обогащение остальных
    предметов из дешёвого станет миграцией;
  * **задача принимает собственный напечатанный ответ.** Физика показывает
    результат округлённым, и с точным допуском автопроверка была бы не
    строгой, а сломанной;
  * **показательная запись разбирается.** «8.7×10^4 Дж» — не экзотика, а
    то, чем физика печатает всё, что больше 10^4 или меньше 10^-3.

Запуск: python -m unittest exercises.fisic.test_answer_spec
"""

from __future__ import annotations

import unittest

from core.answers import NumberSpec, ToleranceKind, significant_digits
from core.generator import Capability
from exercises.fisic.generators import FisicConstructorGenerator


def _config(**over) -> dict:
    """Конфиг того же вида, что лежит в generation_parametrs."""
    cfg = {
        "condition": "Масса #m#, ускорение #a#. Найдите силу.",
        "result_letter": "F",
        "formula": "m * a",
        "dimension": "Н",
        "variables": {
            "m": {"min": 1, "max": 5, "kind": "natural", "dimension": "кг"},
            "a": {"min": 1, "max": 5, "kind": "natural", "dimension": "м/с^2"},
        },
    }
    cfg.update(over)
    return cfg


def _generate(**over):
    return FisicConstructorGenerator(1, "Сила", _config(**over)).generate()


def _printed(task) -> str:
    """Ответ так, как его видит человек, без буквенного обозначения."""
    return task.answer[0].render_plain().split("= ", 1)[-1]


class ExistingConfigsAreEnoughTests(unittest.TestCase):
    """Главный результат пилота: цена обогащения физики — ноль правок в БД."""

    def test_untouched_config_becomes_checkable(self):
        task = _generate()
        self.assertTrue(task.is_checkable)
        self.assertIsInstance(task.answer_spec, NumberSpec)

    def test_dimension_comes_from_the_config(self):
        self.assertEqual(_generate().answer_spec.unit, "Н")

    def test_value_matches_the_condition(self):
        """
        Спецификация несёт результат ТОЙ ЖЕ задачи, а не пересчёт задним
        числом: величины из условия перемножаются в неё.
        """
        import re
        # Размерности здесь убраны нарочно: «м/с^2» содержит цифру, и тест
        # проверял бы разбор условия вместо того, что заявлено.
        task = _generate(variables={
            "m": {"min": 2, "max": 9, "kind": "natural"},
            "a": {"min": 2, "max": 9, "kind": "natural"},
        })
        numbers = [float(n) for n in
                   re.findall(r"\d+(?:\.\d+)?", task.statement[0].render_plain())]
        self.assertEqual(len(numbers), 2)
        self.assertAlmostEqual(task.answer_spec.value,
                               numbers[0] * numbers[1], places=6)

    def test_written_form_is_what_is_shown(self):
        # Показ и проверка сделаны из одной величины — разойтись нечему.
        task = _generate()
        self.assertEqual(f"{task.answer_spec.written} {task.answer_spec.unit}",
                         _printed(task))

    def test_the_whole_subject_is_one_generator(self):
        """
        Обогащён ОДИН класс, а не сорок пять заданий: физический
        конструктор обслуживает все свои разделы. Это и есть причина,
        по которой пилот взят на физике.
        """
        self.assertIn(Capability.CHECKABLE,
                      FisicConstructorGenerator.capabilities)


class TaskAcceptsItsOwnAnswerTests(unittest.TestCase):
    """
    Показ и проверка сделаны из одной величины, поэтому ответ, переписанный
    с экрана, засчитывается по построению.
    """

    CASES = {
        "целое": {"result": {"kind": "natural"}},
        "вещественное": {
            "result": {"kind": "real"},
            "variables": {
                "m": {"min": 0.5, "max": 3, "kind": "real", "decimals": 2,
                      "dimension": "кг"},
                "a": {"min": 0.3, "max": 2, "kind": "real", "decimals": 2,
                      "dimension": "м/с^2"},
            }},
        "показательная запись": {
            "formula": "m * c^2", "dimension": "Дж",
            "result": {"kind": "real"},
            "variables": {"m": {"min": 1, "max": 5, "kind": "natural",
                                "dimension": "кг"}}},
    }

    def test_printed_answer_is_accepted(self):
        for label, over in self.CASES.items():
            for _ in range(20):          # значения случайные — гоняем набор
                with self.subTest(case=label):
                    task = _generate(**over)
                    self.assertTrue(
                        task.answer_spec.check(_printed(task)).accepted,
                        f"{label}: не принят собственный ответ "
                        f"{_printed(task)!r}")

    def test_preview_does_not_lie(self):
        for label, over in self.CASES.items():
            with self.subTest(case=label):
                spec = _generate(**over).answer_spec
                examples = spec.accepted_examples()
                self.assertTrue(examples)
                for example in examples:
                    self.assertTrue(spec.check(example).accepted, example)


class TolerancePolicyTests(unittest.TestCase):
    """Единственное решение пилота, которое стоило измерения."""

    def test_integer_result_is_exact(self):
        # Округления нет, и поблажка означала бы, что 12 сойдёт за 12.4.
        spec = _generate(result={"kind": "natural"}).answer_spec
        self.assertIs(spec.tolerance.kind, ToleranceKind.EXACT)

    def test_real_result_keeps_the_shown_digits(self):
        spec = _generate(
            result={"kind": "real"},
            variables={
                "m": {"min": 1, "max": 1, "kind": "real", "decimals": 3},
                "a": {"min": 3, "max": 3, "kind": "real", "decimals": 3},
            },
            formula="m / a").answer_spec
        self.assertIs(spec.tolerance.kind, ToleranceKind.SIGNIFICANT)
        self.assertEqual(spec.tolerance.amount,
                         significant_digits(spec.written))

    def test_rounded_display_would_fail_on_exact(self):
        """
        Почему допуск обязателен, а не желателен: 1/3 печатается как
        «0.333», а в спецификации лежит 0.3333…. С точным допуском
        задача отвергала бы собственный ответ.
        """
        task = _generate(
            formula="m / a", result={"kind": "real"},
            variables={"m": {"min": 1, "max": 1, "kind": "real"},
                       "a": {"min": 3, "max": 3, "kind": "real"}})
        exact = NumberSpec(value=task.answer_spec.value,
                           unit=task.answer_spec.unit,
                           written=task.answer_spec.written)
        self.assertFalse(exact.check(_printed(task)).accepted)
        self.assertTrue(task.answer_spec.check(_printed(task)).accepted)

    def test_explicit_tolerance_wins(self):
        spec = _generate(answer={"tolerance": {"kind": "relative",
                                               "amount": 0.05}}).answer_spec
        self.assertIs(spec.tolerance.kind, ToleranceKind.RELATIVE)
        self.assertEqual(spec.tolerance.amount, 0.05)
        self.assertTrue(spec.check(f"{spec.value * 1.04:g} Н").accepted)
        self.assertFalse(spec.check(f"{spec.value * 1.2:g} Н").accepted)

    def test_malformed_answer_block_is_refused_loudly(self):
        with self.assertRaises(ValueError):
            _generate(answer={"tolerance": "пять процентов"})


class ScientificNotationTests(unittest.TestCase):
    """
    Показательная запись — не частный случай, а обычный вид ответа в
    физике. До пилота `NumberSpec` считал «×10^4» размерностью.
    """

    def test_mantissa_and_exponent_are_parsed(self):
        spec = NumberSpec(value=87000.0, unit="Дж", written="8.7×10^4")
        self.assertTrue(spec.check("8.7×10^4 Дж").accepted)
        self.assertTrue(spec.check("8.7*10^4 Дж").accepted)
        self.assertTrue(spec.check("8.7e4 Дж").accepted)

    def test_negative_exponent(self):
        spec = NumberSpec(value=0.000345, written="3.45×10^-4")
        self.assertTrue(spec.check("3.45×10^-4").accepted)

    def test_superscript_exponent_survives_normalization(self):
        spec = NumberSpec(value=100.0, written="1×10^2")
        self.assertTrue(spec.check("1×10²").accepted)

    def test_bare_power_of_ten(self):
        self.assertTrue(NumberSpec(value=1000.0).check("10^3").accepted)

    def test_unit_after_the_exponent_still_reads_as_a_unit(self):
        spec = NumberSpec(value=87000.0, unit="Дж", written="8.7×10^4")
        self.assertFalse(spec.check("8.7×10^4 кг").accepted)

    def test_significant_digits_are_counted_on_the_mantissa(self):
        self.assertEqual(significant_digits("8.70×10^4"), 3)
        self.assertEqual(significant_digits("3×10^8"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
