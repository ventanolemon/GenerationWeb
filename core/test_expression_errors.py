"""
Сообщения об ошибках разбора выражения (docs/architecture/interactive_tasks_plan.md, §10.2).

Студент, который отвечает на задание, не знает LaTeX и не читал sympy.
До этих тестов `ExpressionSpec.check()` на любую синтаксическую ошибку
отвечал одной и той же строкой «Выражение не разобрано.» — что именно не
так, студент узнать не мог. Здесь закреплено, что типовые ошибки
называются на языке школьной математики, а внутренняя кухня разбора
наружу не просачивается ни при каких обстоятельствах.
"""

from __future__ import annotations

import re
import unittest

from core.answers import CheckMode, ExpressionSpec, Reason, HOLE


def _spec() -> ExpressionSpec:
    return ExpressionSpec(value="x + 1", symbols=("x", "y"))


class SpecificMessagesTests(unittest.TestCase):
    """
    Каждый пример — реальный ввод из замера в задаче, а не придуманный
    вручную: если формулировка эвристики сместится, тест это заметит.
    """

    def test_missing_closing_bracket(self):
        verdict = _spec().check("(x+1")
        self.assertEqual(verdict.detail, "Не хватает одной закрывающей скобки.")

    def test_missing_closing_bracket_after_unclosed_function(self):
        # Пункт 5 задачи: незакрытая функция сводится к «не хватает
        # скобки» — это тот же дефект с точки зрения студента.
        verdict = _spec().check("x^2 + sin(")
        self.assertEqual(verdict.detail, "Не хватает одной закрывающей скобки.")

    def test_extra_closing_bracket(self):
        verdict = _spec().check("x**2 - 1)")
        self.assertEqual(verdict.detail, "Лишняя закрывающая скобка.")

    def test_expression_breaks_off_on_an_operator(self):
        verdict = _spec().check("x**2 - ")
        self.assertEqual(
            verdict.detail,
            "Выражение обрывается на знаке «−» — после него нужен операнд.")

    def test_two_operators_in_a_row(self):
        verdict = _spec().check("2x +* 1")
        self.assertEqual(verdict.detail, "Два знака подряд: «+*».")

    def test_operator_without_operand_inside_a_call(self):
        verdict = _spec().check("sqrt(-)")
        self.assertEqual(
            verdict.detail,
            "Внутри скобок выражение обрывается на знаке «−» — "
            "после него нужен операнд.")

    def test_empty_parens(self):
        verdict = _spec().check("()")
        self.assertEqual(
            verdict.detail, "Внутри скобок ничего нет — там должен быть операнд.")

    def test_empty_function_call(self):
        verdict = _spec().check("sin()")
        self.assertEqual(
            verdict.detail, "Внутри скобок ничего нет — там должен быть операнд.")

    def test_multiple_missing_closing_brackets(self):
        verdict = _spec().check("((x+1")
        self.assertEqual(verdict.detail, "Не хватает 2 закрывающих скобок.")

    def test_multiple_extra_closing_brackets(self):
        verdict = _spec().check("x+1))")
        self.assertEqual(verdict.detail, "Лишних закрывающих скобок: 2.")


class VerdictShapeUnchangedTests(unittest.TestCase):
    """
    Требование задачи — меняется только `detail`. `reason` остаётся
    `unparsed`, `accepted` остаётся `False` для всех кривых вводов.
    """

    def test_reason_stays_unparsed(self):
        for text in ("(x+1", "x**2 - 1)", "x**2 - ", "2x +* 1", "sqrt(-)", "()"):
            verdict = _spec().check(text)
            self.assertIs(verdict.reason, Reason.UNPARSED, msg=text)
            self.assertFalse(verdict.accepted, msg=text)

    def test_normalized_input_still_reported(self):
        verdict = _spec().check("(x+1")
        self.assertEqual(verdict.normalized_input, "(x+1")


class PreviouslyAcceptedStillAcceptedTests(unittest.TestCase):
    """
    Диагностика причины не должна отбирать НИ ОДНОГО ответа, который
    раньше принимался, — она включается только на пути уже провалившегося
    разбора и не трогает то, что и так разбирается корректно.
    """

    def test_the_real_answer_is_still_accepted(self):
        self.assertTrue(_spec().check("x+1").accepted)

    def test_algebraic_equivalent_is_still_accepted(self):
        spec = ExpressionSpec(value="x**2 - 1", symbols=("x",))
        self.assertTrue(spec.check("(x-1)*(x+1)").accepted)

    def test_implicit_multiplication_is_still_accepted(self):
        spec = ExpressionSpec(value="2*x + 1", symbols=("x",))
        self.assertTrue(spec.check("2x+1").accepted)

    def test_unary_minus_after_operator_is_still_accepted(self):
        spec = ExpressionSpec(value="2*-3", symbols=())
        self.assertTrue(spec.check("2*-3").accepted)

    def test_power_operator_is_still_accepted(self):
        spec = ExpressionSpec(value="x**2", symbols=("x",))
        self.assertTrue(spec.check("x**2").accepted)

    def test_floor_division_still_parses(self):
        # `//` синтаксически валиден для sympy (целочисленное деление) —
        # эвристика «два знака подряд» не должна его перехватывать раньше
        # разбора, раз разбор с ним справляется сам.
        spec = ExpressionSpec(value="3", symbols=())
        verdict = spec.check("3//2")
        self.assertIsNot(verdict.reason, Reason.UNPARSED)


class NoJargonLeaksTests(unittest.TestCase):
    """
    Ни одно сообщение не должно называть внутреннюю кухню разбора:
    ни тип исключения, ни позицию токена, ни имя библиотеки. Список кривых
    строк специально широкий — от одиночных огрехов до полной мешанины.
    """

    BLACKLIST = ("Error", "Traceback", "token", "sympy", "parse",
                "None", "Exception")

    BROKEN_INPUTS = (
        "x**2 - ", "(x+1", "x^2 + sin(", "2x +* 1", "x**2 - 1)", "sqrt(-)",
        "x+", "x-", "x*", "x/", "x^",
        "((x+1)", "(x+1))", ")(", "(((", ")))",
        "x**", "*x", "/x", "x*/2", "x/*2", "x^^2", "x^*2",
        "sin(", "cos(", "sqrt(", "log(",
        "()", "sin()", "cos()", "2*()", "(())", "((()))",
        "x++", "x--", "x+-*", "x**-*2",
        "2..3", "x,,1", "x;y", "x y z (",
        "sin(x", "sin(x))", "((x)", "x)(y",
        "1 + + * 2", "1 - - / 2",
        "x^2+sin(x-", "sqrt(x**2 - ",
        "()()", "(  )", "sin(  )",
        "+", "-", "*", "/", "^", "(", ")",
        "x + (y -", "x * (y /",
    )

    def test_no_forbidden_substrings_in_any_message(self):
        spec = _spec()
        offenders = []
        for text in self.BROKEN_INPUTS:
            verdict = spec.check(text)
            detail = verdict.detail
            for word in self.BLACKLIST:
                if re.search(re.escape(word), detail, re.IGNORECASE):
                    offenders.append((text, detail, word))
        self.assertEqual(
            offenders, [],
            msg=f"Жаргон разбора просочился наружу: {offenders!r}")

    def test_every_message_reads_like_a_sentence(self):
        # Стиль файла: заглавная буква в начале, точка в конце — как у
        # всех прочих сообщений в answers.py.
        spec = _spec()
        for text in self.BROKEN_INPUTS:
            detail = spec.check(text).detail
            if not detail:
                continue
            self.assertTrue(detail[0].isupper(),
                            msg=f"{text!r} -> {detail!r} без заглавной буквы")
            self.assertTrue(detail.endswith("."),
                            msg=f"{text!r} -> {detail!r} без точки на конце")

    def test_fallback_message_is_also_free_of_jargon(self):
        # Одна точка — ни скобок, ни знаков операций, ни лишних символов:
        # ни одна эвристика причину не опознаёт, и это законно. Проверяем,
        # что запасной вариант остаётся человеческим сообщением, а не
        # голым исключением.
        spec = _spec()
        verdict = spec.check(".")
        self.assertIs(verdict.reason, Reason.UNPARSED)
        self.assertEqual(verdict.detail, "Выражение не разобрано.")
        for word in self.BLACKLIST:
            self.assertNotIn(word, verdict.detail)


class StrictModeUnaffectedTests(unittest.TestCase):
    """Диагностика причины — общий код `_parse`, а не мягкого режима."""

    def test_strict_mode_gets_the_same_specific_message(self):
        verdict = _spec().check("(x+1", mode=CheckMode.STRICT)
        self.assertEqual(verdict.detail, "Не хватает одной закрывающей скобки.")
        self.assertIs(verdict.reason, Reason.UNPARSED)


if __name__ == "__main__":
    unittest.main()


class FormulaHolesTests(unittest.TestCase):
    """
    Пустое место из палитры формул (этап 7, §10.2).

    Кнопку «Ответить» клиент при незаполненных местах не даёт, но ответ
    может прийти и не от него — набранным руками или из другого клиента.
    Сообщение «в выражении есть недопустимые символы» здесь особенно
    бестолково: студент видит в своей формуле пустой квадратик и ровно
    про него спрашивает.
    """

    SPEC = ExpressionSpec(value="x**2 - 1", symbols=("x",))

    def test_a_hole_is_named_as_a_hole(self):
        for text in (HOLE, f"x + {HOLE}", f"\\frac{{{HOLE}}}{{3}}"):
            with self.subTest(text=text):
                verdict = self.SPEC.check(text)
                self.assertFalse(verdict.accepted)
                self.assertIn("незаполненные", verdict.detail)

    def test_a_filled_formula_is_unaffected(self):
        self.assertTrue(self.SPEC.check("x**2 - 1").accepted)

    def test_the_symbol_matches_the_client(self):
        """
        Символ объявлен дважды — в ядре и во фронте, — потому что ставит
        его клиент, а узнавать обязана проверка. Разъехавшись, они дадут
        «недопустимые символы» там, где место просто не заполнено.
        """
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        source = (root / "frontend" / "src" / "formula" / "fields.ts")
        if not source.exists():
            self.skipTest("фронта нет в этом репозитории")
        found = re.search(r'export const HOLE = "(.+?)"',
                          source.read_text(encoding="utf-8"))
        self.assertIsNotNone(found, "во фронте не нашлось объявления HOLE")
        self.assertEqual(found.group(1), HOLE)
