"""
Тесты спецификации ответа.

Отдельно закреплены четыре условия расширяемости из §5.1 плана и главная
опасность из §5 — все они такие, что нарушение не видно на глаз и
вылезает через месяцы.
"""

import unittest

from core.answers import (
    AnswerSpec, CheckMode, ExpressionError, ExpressionSpec, NumberSpec,
    Reason, SlotsSpec, TextSpec, Tolerance, ToleranceKind, normalize,
)


# ======================================================================
#  Пол нормализации (§5.1, условие 2)
# ======================================================================

class NormalizationFloorTests(unittest.TestCase):
    """Строгость начинается ПОСЛЕ приведения к канону, а не вместо него."""

    def test_unicode_minus_becomes_hyphen(self):
        self.assertEqual(normalize("−5"), "-5")

    def test_multiplication_signs_unify(self):
        for sign in ("×", "·", "∙", "⋅"):
            self.assertEqual(normalize(f"2{sign}3"), "2*3")

    def test_decimal_comma_between_digits(self):
        self.assertEqual(normalize("1,5"), "1.5")

    def test_comma_outside_digits_is_left_alone(self):
        # Иначе перечисление «красный, синий» превратилось бы в мусор.
        self.assertEqual(normalize("красный, синий"), "красный, синий")

    def test_superscripts_expand(self):
        self.assertEqual(normalize("x²"), "x^2")

    def test_nonbreaking_spaces_collapse(self):
        self.assertEqual(normalize("9.8 м/с"), "9.8 м/с")

    def test_case_is_not_folded(self):
        # «м» и «М» — милли и мега; регистр это настройка, а не пол.
        self.assertEqual(normalize("мМ"), "мМ")


class StrictModeStillNormalizesTests(unittest.TestCase):
    """
    Ключевое: строгий режим — НЕ побайтовое совпадение.

    Без этого «строго» означает «наберите те же символы, что и я»,
    и режим бесполезен.
    """

    def test_strict_number_accepts_comma_and_unicode_minus(self):
        spec = NumberSpec(value=-1.5, mode=CheckMode.STRICT)
        self.assertTrue(spec.check("−1,5").accepted)

    def test_strict_expression_accepts_unicode_multiplication(self):
        spec = ExpressionSpec(value="2*x", symbols=("x",),
                              mode=CheckMode.STRICT)
        self.assertTrue(spec.check("2×x").accepted)

    def test_strict_text_accepts_padded_input(self):
        spec = TextSpec(value="ускорение", mode=CheckMode.STRICT)
        self.assertTrue(spec.check("  ускорение  ").accepted)


# ======================================================================
#  Режим — перечисление, а не bool (§5.1, условие 1)
# ======================================================================

class CheckModeIsEnumTests(unittest.TestCase):

    def test_two_values_today(self):
        self.assertEqual(
            {m.value for m in CheckMode}, {"soft", "strict"})

    def test_serializes_as_readable_string(self):
        # В БД и в логе должно читаться «soft», а не 0.
        spec = NumberSpec(value=1.0, mode=CheckMode.STRICT)
        self.assertEqual(spec.to_dict()["mode"], "strict")

    def test_mode_is_not_boolean(self):
        # Защита от «упростим до флага»: bool(CheckMode.SOFT) ничего
        # осмысленного не значит, и код на это опираться не должен.
        self.assertNotIsInstance(CheckMode.SOFT, bool)


# ======================================================================
#  Вердикт несёт режим (§5.1, условие 4)
# ======================================================================

class VerdictCarriesModeTests(unittest.TestCase):
    """
    Режим едет вместе с вердиктом, чтобы этап 3 записал его в попытку.

    Без этого переключение тумблера задним числом меняет смысл всей
    накопленной статистики.
    """

    def test_verdict_reports_spec_mode(self):
        spec = NumberSpec(value=2.0, mode=CheckMode.STRICT)
        self.assertIs(spec.check("2").mode, CheckMode.STRICT)

    def test_per_call_override_is_reported(self):
        spec = NumberSpec(value=2.0, mode=CheckMode.SOFT)
        self.assertIs(spec.check("2", mode=CheckMode.STRICT).mode,
                      CheckMode.STRICT)

    def test_mode_present_in_serialized_verdict(self):
        verdict = TextSpec(value="да").check("да")
        self.assertEqual(verdict.to_dict()["mode"], "soft")


# ======================================================================
#  Пустая настройка инертна (§5.1, условие 3)
# ======================================================================

class EmptyTuningIsInertTests(unittest.TestCase):
    """
    Отсутствие настройки и пустая настройка обязаны давать посимвольно
    одинаковое поведение.

    Иначе в день, когда поле появится в схеме, тихо поедут все
    существующие задания — а заметят это по жалобам студентов.
    """

    CASES = (
        (NumberSpec(value=9.8, tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1),
                    unit="м/с^2"),
         ("9.8 м/с^2", "9.85 м/с^2", "10 м/с^2", "9.8", "", "abc")),
        (TextSpec(value="ускорение", alternatives=("acceleration",)),
         ("ускорение", "ускорние", "acceleration", "скорость", "")),
        (ExpressionSpec(value="x**2-1", symbols=("x",)),
         ("x**2-1", "(x-1)*(x+1)", "x^2 - 1", "x+1", "")),
    )

    def test_verdicts_identical_with_and_without_empty_tuning(self):
        for bare, inputs in self.CASES:
            with_empty = AnswerSpec.from_dict(
                {**bare.to_dict(), "tuning": {}})
            for mode in (CheckMode.SOFT, CheckMode.STRICT):
                for text in inputs:
                    with self.subTest(kind=bare.kind, mode=mode, text=text):
                        self.assertEqual(
                            bare.check(text, mode=mode),
                            with_empty.check(text, mode=mode))

    def test_empty_tuning_is_not_serialized(self):
        # Половина инертности — не писать пустое поле вовсе.
        self.assertNotIn("tuning", NumberSpec(value=1.0).to_dict())

    def test_declared_tuning_survives_round_trip(self):
        spec = AnswerSpec.from_dict(
            {**NumberSpec(value=1.0).to_dict(), "tuning": {"note": "x"}})
        self.assertEqual(spec.to_dict()["tuning"], {"note": "x"})


# ======================================================================
#  Число
# ======================================================================

class NumberSpecTests(unittest.TestCase):

    def test_absolute_tolerance(self):
        spec = NumberSpec(value=9.8,
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1))
        self.assertTrue(spec.check("9.85").accepted)
        self.assertFalse(spec.check("10.5").accepted)

    def test_relative_tolerance(self):
        spec = NumberSpec(value=1000.0,
                          tolerance=Tolerance(ToleranceKind.RELATIVE, 0.01))
        self.assertTrue(spec.check("1005").accepted)
        self.assertFalse(spec.check("1200").accepted)

    def test_significant_digits_tolerance(self):
        spec = NumberSpec(value=3.14159,
                          tolerance=Tolerance(ToleranceKind.SIGNIFICANT, 3))
        self.assertTrue(spec.check("3.14").accepted)
        self.assertFalse(spec.check("3.2").accepted)

    def test_unit_must_match_when_declared(self):
        spec = NumberSpec(value=9.8, unit="м/с^2")
        self.assertTrue(spec.check("9.8 м/с^2").accepted)
        wrong = spec.check("9.8 км/ч")
        self.assertFalse(wrong.accepted)
        self.assertIs(wrong.reason, Reason.WRONG_UNIT)

    def test_missing_unit_is_rejected_when_declared(self):
        self.assertFalse(NumberSpec(value=9.8, unit="м/с").check("9.8").accepted)

    def test_no_unit_declared_ignores_trailing_text(self):
        # Размерности нет — значит и требовать нечего.
        self.assertTrue(NumberSpec(value=5.0).check("5").accepted)

    def test_thousands_spaces_are_tolerated(self):
        self.assertTrue(NumberSpec(value=1000.0).check("1 000").accepted)

    def test_strict_requires_written_form(self):
        spec = NumberSpec(value=0.5, written="0.50",
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.01))
        self.assertTrue(spec.check("0.50", mode=CheckMode.STRICT).accepted)
        loose = spec.check("0.5", mode=CheckMode.STRICT)
        self.assertFalse(loose.accepted)
        self.assertIs(loose.reason, Reason.WRONG_FORM)

    def test_soft_ignores_written_form(self):
        spec = NumberSpec(value=0.5, written="0.50",
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.01))
        self.assertTrue(spec.check("0.5", mode=CheckMode.SOFT).accepted)

    def test_unparsed_input(self):
        self.assertIs(NumberSpec(value=1.0).check("около трёх").reason,
                      Reason.UNPARSED)

    def test_empty_input(self):
        self.assertIs(NumberSpec(value=1.0).check("   ").reason, Reason.EMPTY)


class WrittenSignificantDigitsTests(unittest.TestCase):

    def test_counts(self):
        # Счётчик стал публичным: им пользуется не только строгий режим, но
        # и генератор, который показывает округлённый ответ и обязан
        # принимать ровно то, что показал.
        from core.answers import significant_digits as count
        self.assertEqual(count("0.50"), 2)
        self.assertEqual(count("0.5"), 1)
        self.assertEqual(count("1.50"), 3)
        self.assertEqual(count("0.050"), 2)
        self.assertEqual(count("100"), 3)
        self.assertEqual(count("0"), 1)
        self.assertEqual(count("-2.5e3"), 2)
        # Показательная запись считается по мантиссе.
        self.assertEqual(count("8.70×10^4"), 3)


# ======================================================================
#  Строка
# ======================================================================

class TextSpecTests(unittest.TestCase):

    def test_exact_match(self):
        self.assertTrue(TextSpec(value="ускорение").check("ускорение").accepted)

    def test_case_insensitive_by_default(self):
        self.assertTrue(TextSpec(value="Ускорение").check("ускорение").accepted)

    def test_case_sensitive_when_asked(self):
        spec = TextSpec(value="Ом", case_sensitive=True)
        self.assertFalse(spec.check("ом").accepted)

    def test_alternatives_accepted(self):
        spec = TextSpec(value="ускорение", alternatives=("acceleration",))
        self.assertTrue(spec.check("acceleration").accepted)

    def test_typo_accepted_in_soft_mode(self):
        verdict = TextSpec(value="ускорение").check("ускорене")
        self.assertTrue(verdict.accepted)
        self.assertIs(verdict.reason, Reason.TYPO)

    def test_typo_rejected_in_strict_mode(self):
        spec = TextSpec(value="ускорение")
        self.assertFalse(spec.check("ускорене", mode=CheckMode.STRICT).accepted)

    def test_typo_budget_respected(self):
        # «ускорнеие» — перестановка, по Левенштейну это две правки.
        spec = TextSpec(value="ускорение", max_edits=1)
        self.assertFalse(spec.check("ускорнеие").accepted)
        self.assertTrue(
            TextSpec(value="ускорение", max_edits=2).check("ускорнеие").accepted)

    def test_case_only_difference_is_not_a_typo_when_case_matters(self):
        # Иначе допуск на опечатку молча отменяет case_sensitive.
        spec = TextSpec(value="Ом", case_sensitive=True, max_edits=1)
        self.assertFalse(spec.check("ом").accepted)


# ======================================================================
#  Выражение — главная опасность §5
# ======================================================================

class ExpressionEquivalenceTests(unittest.TestCase):

    def test_soft_accepts_algebraic_rearrangement(self):
        spec = ExpressionSpec(value="x**2-1", symbols=("x",))
        verdict = spec.check("(x-1)*(x+1)")
        self.assertTrue(verdict.accepted)
        self.assertIs(verdict.reason, Reason.EQUIVALENT)

    def test_strict_rejects_different_form(self):
        spec = ExpressionSpec(value="x**2-1", symbols=("x",),
                              mode=CheckMode.STRICT)
        verdict = spec.check("(x-1)*(x+1)")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.WRONG_FORM)

    def test_commutativity_passes_both_modes(self):
        # 2*x и x*2 — одна форма с точностью до канонизации, не «другая».
        spec = ExpressionSpec(value="2*x", symbols=("x",))
        for mode in (CheckMode.SOFT, CheckMode.STRICT):
            self.assertTrue(spec.check("x*2", mode=mode).accepted)

    def test_caret_is_accepted_as_power(self):
        spec = ExpressionSpec(value="x**2", symbols=("x",))
        self.assertTrue(spec.check("x^2").accepted)


class RestatedConditionIsRejectedTests(unittest.TestCase):
    """
    Опасность §5 в чистом виде.

    Для «упростите (x**2-1)/(x-1)» проверка simplify(ввод − ответ) == 0
    принимает САМО УСЛОВИЕ: оно эквивалентно ответу. То есть задание
    засчитывает нерешённое. Это не строгость и не мягкость — это
    неверное направление проверки.
    """

    def spec(self):
        return ExpressionSpec(
            value="x+1",
            symbols=("x",),
            reject_equivalent_to=("(x**2-1)/(x-1)",))

    def test_plain_soft_check_would_have_accepted_the_statement(self):
        # Без списка запрета мягкий режим действительно принимает условие —
        # тест фиксирует, что опасность реальна, а не гипотетическая.
        naive = ExpressionSpec(value="x+1", symbols=("x",))
        self.assertTrue(naive.check("(x**2-1)/(x-1)").accepted)

    def test_restated_statement_is_rejected(self):
        verdict = self.spec().check("(x**2-1)/(x-1)")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.RESTATED)

    def test_real_answer_still_accepted(self):
        self.assertTrue(self.spec().check("x+1").accepted)

    def test_rejection_holds_in_strict_mode_too(self):
        verdict = self.spec().check("(x**2-1)/(x-1)", mode=CheckMode.STRICT)
        self.assertFalse(verdict.accepted)


class ExpressionSafetyTests(unittest.TestCase):
    """
    Разбор выражения — исполнение ввода. Белый список работает ДО разбора.

    Та же дыра, что в §9 плана: если пускать произвольный текст в
    parse_expr, проверять разобранное дерево уже поздно.
    """

    def spec(self):
        return ExpressionSpec(value="x+1", symbols=("x",))

    def test_dunder_is_refused(self):
        verdict = self.spec().check("x.__class__")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.UNPARSED)

    def test_unknown_name_is_refused(self):
        self.assertIs(self.spec().check("os").reason, Reason.UNPARSED)

    def test_undeclared_symbol_is_refused(self):
        # y не объявлен — принимать его молча значит принимать что угодно.
        self.assertIs(self.spec().check("y+1").reason, Reason.UNPARSED)

    def test_allowed_function_passes(self):
        spec = ExpressionSpec(value="sqrt(x)", symbols=("x",))
        self.assertTrue(spec.check("sqrt(x)").accepted)

    def test_parse_raises_typed_error(self):
        with self.assertRaises(ExpressionError):
            self.spec()._parse("import os")


# ======================================================================
#  Слоты
# ======================================================================

class SlotsSpecTests(unittest.TestCase):

    def spec(self):
        return SlotsSpec(slots=(
            ("v", NumberSpec(value=10.0, unit="м/с")),
            ("t", NumberSpec(value=2.0, unit="с")),
        ))

    def test_named_input(self):
        self.assertTrue(self.spec().check("v=10 м/с; t=2 с").accepted)

    def test_positional_input(self):
        self.assertTrue(self.spec().check("10 м/с; 2 с").accepted)

    def test_one_wrong_slot_fails_the_whole_answer(self):
        verdict = self.spec().check("v=10 м/с; t=5 с")
        self.assertFalse(verdict.accepted)
        self.assertIn("t", verdict.detail)

    def test_per_slot_verdicts_exposed(self):
        verdict = self.spec().check("v=10 м/с; t=5 с")
        by_name = dict(verdict.slots)
        self.assertTrue(by_name["v"].accepted)
        self.assertFalse(by_name["t"].accepted)

    def test_dictionary_entry_point(self):
        verdict = self.spec().check_slots({"v": "10 м/с", "t": "2 с"})
        self.assertTrue(verdict.accepted)

    def test_mode_propagates_to_slots(self):
        spec = SlotsSpec(slots=(("a", TextSpec(value="ускорение")),))
        self.assertTrue(spec.check("a=ускорене", mode=CheckMode.SOFT).accepted)
        self.assertFalse(
            spec.check("a=ускорене", mode=CheckMode.STRICT).accepted)

    def test_mixed_slot_kinds(self):
        spec = SlotsSpec(slots=(
            ("n", NumberSpec(value=3.0)),
            ("name", TextSpec(value="ток")),
        ))
        self.assertTrue(spec.check("n=3; name=ток").accepted)


# ======================================================================
#  Предпросмотр «что примут» (§5)
# ======================================================================

class PreviewIsHonestTests(unittest.TestCase):
    """
    Каждый пример из accepted_examples() обязан реально проходить check().

    Список «эти ответы будут засчитаны» — единственное, что заставляет
    преподавателя доверять механизму. Соврав здесь один раз, мы получим
    выключенный интерактив и никакой обратной связи о причине.
    """

    SPECS = (
        NumberSpec(value=9.8, tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1),
                   unit="м/с^2"),
        NumberSpec(value=1000.0,
                   tolerance=Tolerance(ToleranceKind.RELATIVE, 0.01)),
        NumberSpec(value=0.5, written="0.50",
                   tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.01)),
        TextSpec(value="ускорение", alternatives=("acceleration",)),
        TextSpec(value="Ом", case_sensitive=True, max_edits=0),
        ExpressionSpec(value="x**2-1", symbols=("x",)),
        ExpressionSpec(value="x+1", symbols=("x",),
                       reject_equivalent_to=("(x**2-1)/(x-1)",)),
    )

    def test_every_example_passes_its_own_check(self):
        for spec in self.SPECS:
            for mode in (CheckMode.SOFT, CheckMode.STRICT):
                for example in spec.accepted_examples(mode=mode):
                    with self.subTest(kind=spec.kind, mode=mode, ex=example):
                        self.assertTrue(
                            spec.check(example, mode=mode).accepted,
                            f"обещали принять {example!r}, а не приняли")

    def test_preview_is_never_empty(self):
        for spec in self.SPECS:
            with self.subTest(kind=spec.kind):
                self.assertTrue(spec.accepted_examples())

    def test_slots_preview_passes(self):
        spec = SlotsSpec(slots=(
            ("v", NumberSpec(value=10.0, unit="м/с")),
            ("t", NumberSpec(value=2.0, unit="с")),
        ))
        for example in spec.accepted_examples():
            self.assertTrue(spec.check(example).accepted)


# ======================================================================
#  Показ выводится из данных (§1)
# ======================================================================

class DisplayIsDerivedTests(unittest.TestCase):

    def test_number_shows_value_and_unit(self):
        blocks = NumberSpec(value=9.8, unit="м/с^2").display_blocks()
        self.assertEqual(blocks[0].render_plain(), "9.8 м/с^2")

    def test_number_shows_canonical_written_form(self):
        blocks = NumberSpec(value=0.5, written="0.50").display_blocks()
        self.assertEqual(blocks[0].render_plain(), "0.50")

    def test_expression_becomes_latex(self):
        blocks = ExpressionSpec(value="x**2-1", symbols=("x",)).display_blocks()
        self.assertEqual(blocks[0].to_dict()["type"], "formula")

    def test_slots_show_every_field(self):
        spec = SlotsSpec(slots=(
            ("v", NumberSpec(value=10.0, unit="м/с")),
            ("t", NumberSpec(value=2.0, unit="с")),
        ))
        shown = [b.render_plain() for b in spec.display_blocks()]
        self.assertEqual(shown, ["v: 10 м/с", "t: 2 с"])


# ======================================================================
#  Сериализация
# ======================================================================

class SerializationTests(unittest.TestCase):

    SPECS = (
        NumberSpec(value=9.8, tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1),
                   unit="м/с^2", written="9.80", mode=CheckMode.STRICT),
        TextSpec(value="ускорение", alternatives=("acceleration",),
                 case_sensitive=True, max_edits=2),
        ExpressionSpec(value="x**2-1", symbols=("x", "y"),
                       reject_equivalent_to=("(x-1)*(x+1)",)),
        SlotsSpec(slots=(
            ("v", NumberSpec(value=10.0, unit="м/с")),
            ("name", TextSpec(value="ток")),
        )),
    )

    def test_round_trip_preserves_behaviour(self):
        probes = ("9.8 м/с^2", "9.80 м/с^2", "ускорение", "x**2-1",
                  "v=10 м/с; name=ток", "")
        for spec in self.SPECS:
            restored = AnswerSpec.from_dict(spec.to_dict())
            for mode in (CheckMode.SOFT, CheckMode.STRICT):
                for probe in probes:
                    with self.subTest(kind=spec.kind, mode=mode, probe=probe):
                        self.assertEqual(spec.check(probe, mode=mode),
                                         restored.check(probe, mode=mode))

    def test_round_trip_is_stable_dict(self):
        for spec in self.SPECS:
            once = spec.to_dict()
            twice = AnswerSpec.from_dict(once).to_dict()
            self.assertEqual(once, twice)

    def test_json_serializable(self):
        import json
        for spec in self.SPECS:
            json.dumps(spec.to_dict())

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            AnswerSpec.from_dict({"kind": "пирожок"})

    def test_nested_slots_round_trip(self):
        spec = SlotsSpec(slots=(("a", SlotsSpec(slots=(
            ("b", NumberSpec(value=1.0)),))),))
        self.assertEqual(spec.to_dict(),
                         AnswerSpec.from_dict(spec.to_dict()).to_dict())


if __name__ == "__main__":
    unittest.main()
