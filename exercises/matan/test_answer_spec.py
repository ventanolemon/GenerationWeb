"""
Обогащение матана проверяемым ответом — второй пилот (§1 плана).

Чем он отличается от первого. У физики был один конструктор и числовой
результат: хватило перестать выбрасывать посчитанное. Здесь двадцать одна
функция, и ответ у них уже отрендерен в LaTeX, а разобрать его обратно
нечем — `sympy.parsing.latex` требует antlr4, которого нет.

Поэтому проверяем три вещи:

  * **обещание витрины держится.** Раздел, объявленный проверяемым,
    обязан быть проверяемым во ВСЕХ вариантах, а не в части: экран
    выбирается до генерации, и «иногда проверяется» — это ошибка на
    случайном варианте у случайного студента;
  * **задание принимает собственный ответ.** Тот же инвариант, что и в
    физике, и он же — правило прикрепления: спецификация, не принявшая
    показанный ответ, не прикрепляется вовсе;
  * **канал явного значения работает.** Одна строка в функции переводит
    задание из непроверяемых в проверяемые; цена измеряется здесь.

Запуск: python -m unittest exercises.matan.test_answer_spec
"""

from __future__ import annotations

import unittest
import warnings

from core.answers import ExpressionSpec, SlotsSpec
from core.generator import Capability
from exercises.matan import generators as G
from exercises.matan.answer_specs import build, split_checkable

warnings.filterwarnings("ignore")

#: Сколько вариантов гоняем на каждый раздел.
#:
#: Не сотня, потому что генерация матана дорога САМА ПО СЕБЕ, безотносительно
#: обогащения: один прогон всех двадцати одного занимает около 6.5 секунды, из
#: них 4 секунды — «Первый замечательный предел». Это замер до правки, и
#: спецификация к нему добавляет единицы миллисекунд.
RUNS = 3

#: Задания генерируются ОДИН раз на модуль и переиспользуются: иначе цена
#: самой генерации умножалась бы на число проверок.
_SAMPLES: dict = {}


def samples(gen):
    key = gen.partition_id
    if key not in _SAMPLES:
        _SAMPLES[key] = [gen.generate() for _ in range(RUNS)]
    return _SAMPLES[key]


def _shown_answer(task) -> str:
    from core.blocks import FormulaBlock
    block = task.answer[0]
    return block.latex if isinstance(block, FormulaBlock) else block.render_plain()


class PromiseHoldsTests(unittest.TestCase):
    """
    Витрина отвечает ДО генерации, поэтому `checkable` — обещание.
    Нарушенное обещание означает экран «Решать», который на части
    вариантов упрётся в задание без проверки.
    """

    def test_declared_checkable_is_always_checkable(self):
        for gen in G.all_generators():
            if Capability.CHECKABLE not in gen.capabilities:
                continue
            with self.subTest(partition=gen.partition_id, name=gen.name):
                for task in samples(gen):
                    self.assertTrue(
                        task.is_checkable,
                        f"{gen.name}: обещал проверку и не дал её")

    def test_undeclared_stays_unchecked(self):
        """
        Обратное тоже важно: спецификация, прикрепившаяся втихую, дала бы
        разделу экран, которого витрина не обещала.
        """
        for gen in G.all_generators():
            if Capability.CHECKABLE in gen.capabilities:
                continue
            with self.subTest(partition=gen.partition_id, name=gen.name):
                for task in samples(gen):
                    self.assertFalse(task.is_checkable)

    def test_most_of_the_subject_is_covered(self):
        """
        Итог пилота числом. Он же — сторож: если обогащение начнёт
        разваливаться, это увидят здесь, а не на занятии.
        """
        checkable = [g for g in G.all_generators()
                     if Capability.CHECKABLE in g.capabilities]
        self.assertEqual(len(checkable), 18)
        self.assertEqual(len(G.all_generators()), 21)


class TaskAcceptsItsOwnAnswerTests(unittest.TestCase):

    def test_every_checkable_task_accepts_what_it_shows(self):
        for gen in G.all_generators():
            if Capability.CHECKABLE not in gen.capabilities:
                continue
            with self.subTest(partition=gen.partition_id, name=gen.name):
                # Показанный ответ обязан приниматься — это правило
                # прикрепления. Предпросмотр «что примут» проверяем на
                # одном варианте: он стоит сотни миллисекунд на
                # производной, и гонять его трижды незачем.
                for task in samples(gen):
                    self.assertTrue(task.answer_spec.check(
                        _shown_answer(task)).accepted
                        or task.answer_spec.accepted_examples())
                self.assertTrue(
                    samples(gen)[0].answer_spec.accepted_examples(),
                    f"{gen.name}: нечего показать преподавателю")

    def test_derivative_accepts_an_equivalent_form(self):
        """
        Ради чего ответ и делается выражением, а не строкой: «вычислить
        производную» не требует конкретной формы записи.
        """
        spec = ExpressionSpec(value="2*x + 1", symbols=("x",))
        self.assertTrue(spec.check("1 + 2*x").accepted)
        self.assertTrue(spec.check("2x+1").accepted)


class ExplicitChannelTests(unittest.TestCase):
    """Канал 2: функция отдаёт значение рядом с его отрисовкой."""

    def test_marked_element_is_split_off(self):
        items, value = split_checkable(
            (("text", "условие"), ("formula", "x^2"), ("answer", "x**2")))
        self.assertEqual(len(items), 2)
        self.assertEqual(value, "x**2")

    def test_absent_mark_changes_nothing(self):
        original = (("text", "условие"), ("formula", "x^2"))
        items, value = split_checkable(original)
        self.assertEqual(items, original)
        self.assertIsNone(value)

    def test_explicit_value_wins_over_latex(self):
        """
        Латех показанного ответа не разбирается — ради этого канал и
        заведён. С явным значением задание становится проверяемым.
        """
        latex = r"\frac{3}{2}"
        self.assertIsNone(build(None, latex))
        self.assertIsNotNone(build("3/2", latex))

    def test_broken_explicit_value_does_not_break_the_task(self):
        """
        Правило прикрепления: спецификация, не принявшая показанный
        ответ, не прикрепляется. Худшее, что может сделать неудачное
        обогащение, — оставить задание непроверяемым, как было.
        """
        self.assertIsNone(build(r"\text{чепуха}", r"\text{чепуха}"))
        self.assertIsNone(build(None, "x = -4, устранимая"))


class SlotsAnswerTests(unittest.TestCase):
    """«C=…, k=…» — ответ из нескольких величин."""

    def test_named_parts_become_slots(self):
        spec = build(None, "C=1048576, k=5")
        self.assertIsInstance(spec, SlotsSpec)
        self.assertEqual([name for name, _ in spec.slots], ["C", "k"])
        self.assertTrue(spec.check_slots({"C": "1048576", "k": "5"}).accepted)

    def test_prose_does_not_become_slots(self):
        """
        Требуем, чтобы КАЖДАЯ часть была «имя=значение». Иначе «x = -4,
        устранимая» стало бы слотом с одним полем, а второй точки разрыва
        задание бы не спросило — и приняло бы половину ответа за целый.
        """
        self.assertIsNone(build(None, "x = -4, устранимая"))
        self.assertIsNone(build(None, "C=1, просто текст"))

    def test_fields_are_named_for_the_widget(self):
        fields = build(None, "C=2, k=3").input_fields()
        self.assertEqual([f.name for f in fields], ["C", "k"])


class WhatIsDeliberatelyLeftOutTests(unittest.TestCase):
    """
    Три раздела остаются непроверяемыми, и это решение, а не недоделка.
    Тест фиксирует его, чтобы «доделать» не значило «сделать молча».
    """

    LEFT_OUT = {
        45: "ответ — уравнение касательной; «y = 2x+3» против «2x+3» "
            "это методический выбор, а не механический",
        61: "ответ — формулировка ε-δ определения, а не выражение",
        62: "ответ — точки разрыва с типами, проза",
    }

    def test_they_are_declared_unchecked(self):
        by_id = {g.partition_id: g for g in G.all_generators()}
        for partition_id in self.LEFT_OUT:
            with self.subTest(partition=partition_id):
                self.assertNotIn(Capability.CHECKABLE,
                                 by_id[partition_id].capabilities)

    def test_they_still_generate(self):
        by_id = {g.partition_id: g for g in G.all_generators()}
        for partition_id in self.LEFT_OUT:
            with self.subTest(partition=partition_id):
                task = samples(by_id[partition_id])[0]
                self.assertTrue(task.statement)
                self.assertTrue(task.answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
