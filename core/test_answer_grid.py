"""
Сетка ответа: матрица, таблица, расписание — одним механизмом.

Центральное решение, которое здесь закрепляется: **отдельного вида ответа
для матриц нет.** Матрица — это сетка типизированных ячеек, а сетка
типизированных ячеек уже была: у каждого слота своя спецификация, свой
вердикт и своё поле ввода. Форма (`shape`) добавляет к ним геометрию, и
всё.

Из чего следует практическая выгода: тем же механизмом получается
табличный ввод вообще. Таблица истинности, расписание, «заполните
таблицу» — это набор слотов с формой, а не новая сущность.

Проверяем поэтому не «матрица работает», а что механизм ОДИН:
  * матрица и произвольная таблица дают спецификацию одного вида;
  * вердикт по-прежнему повердиктный, и место ошибки называется
    по-человечески, а не «r2c1»;
  * форма переживает сериализацию — иначе изолированное исполнение
    графа (§9) вернуло бы сетку столбиком.
"""

from __future__ import annotations

import unittest

from core.answers import (AnswerSpec, ExpressionSpec, NumberSpec, SlotsSpec,
                          Tolerance, ToleranceKind)
from core.widgets import resolve_widget, widgets_for


def _matrix(rows):
    import sympy
    return sympy.Matrix(rows)


class OneMechanismTests(unittest.TestCase):

    def test_matrix_is_just_slots_with_a_shape(self):
        spec = SlotsSpec.from_grid(_matrix([[1, 2], [3, 4]]))
        self.assertIsInstance(spec, SlotsSpec)
        self.assertEqual(spec.kind, "slots")
        self.assertEqual(spec.shape, (2, 2))
        self.assertEqual(len(spec.slots), 4)

    def test_a_plain_table_goes_the_same_way(self):
        """Расписание — та же сетка. Ради этого поле и названо `shape`."""
        spec = SlotsSpec.from_grid([["да", "нет"], ["нет", "да"]],
                                   header=["p", "q"])
        self.assertEqual(spec.shape, (2, 2))
        self.assertTrue(spec.check_slots(
            {"r1c1": "да", "r1c2": "нет",
             "r2c1": "нет", "r2c2": "да"}).accepted)

    def test_cell_kind_follows_the_value(self):
        """
        В одной таблице соседствуют «5» и «sqrt(2)». Просить автора
        расписать вид каждой ячейки значило бы просить описать то, что и
        так видно.
        """
        import sympy
        spec = SlotsSpec.from_grid([[5, sympy.sqrt(2)], ["x + 1", "-3"]])
        kinds = [inner.kind for _, inner in spec.slots]
        self.assertEqual(kinds, ["number", "expression", "expression", "number"])

    def test_row_vector_needs_no_extra_nesting(self):
        spec = SlotsSpec.from_grid([1, 2, 3])
        self.assertEqual(spec.shape, (1, 3))

    def test_mismatched_shape_is_refused(self):
        with self.assertRaises(ValueError):
            SlotsSpec(slots=(("a", NumberSpec(value=1)),), shape=(2, 2))

    def test_ragged_grid_is_refused(self):
        with self.assertRaises(ValueError):
            SlotsSpec.from_grid([[1, 2], [3]])

    def test_empty_grid_is_refused(self):
        with self.assertRaises(ValueError):
            SlotsSpec.from_grid([])


class ToleranceAppliesToEveryCellTests(unittest.TestCase):

    def test_shared_tolerance(self):
        spec = SlotsSpec.from_grid(
            [[1.0, 2.0]], tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1))
        self.assertTrue(spec.check_slots({"r1c1": "1.05", "r1c2": "2"}).accepted)
        self.assertFalse(spec.check_slots({"r1c1": "1.5", "r1c2": "2"}).accepted)

    def test_exact_by_default(self):
        spec = SlotsSpec.from_grid([[1.0]])
        self.assertFalse(spec.check_slots({"r1c1": "1.05"}).accepted)


class VerdictNamesThePlaceTests(unittest.TestCase):
    """
    Имена ячеек технические. Показывать их человеку — значит требовать от
    него знать внутреннее устройство, чтобы понять, где он ошибся.
    """

    def setUp(self):
        self.spec = SlotsSpec.from_grid(_matrix([[1, 2], [3, 4]]))

    def test_place_instead_of_identifier(self):
        verdict = self.spec.check_slots(
            {"r1c1": "1", "r1c2": "2", "r2c1": "9", "r2c2": "4"})
        self.assertFalse(verdict.accepted)
        self.assertIn("строка 2, столбец 1", verdict.detail)
        self.assertNotIn("r2c1", verdict.detail)

    def test_per_slot_verdicts_are_still_there(self):
        # Разбор по ячейкам никуда не делся — по нему интерфейс подсветит
        # конкретное поле, а не покажет одну строку текста.
        verdict = self.spec.check_slots(
            {"r1c1": "1", "r1c2": "2", "r2c1": "9", "r2c2": "4"})
        by_name = dict(verdict.slots)
        self.assertTrue(by_name["r1c1"].accepted)
        self.assertFalse(by_name["r2c1"].accepted)

    def test_unshaped_slots_keep_their_names(self):
        spec = SlotsSpec(slots=(("скорость", NumberSpec(value=1)),))
        self.assertIn("скорость", spec.check_slots({"скорость": "9"}).detail)


class DisplayAndFieldsTests(unittest.TestCase):

    def setUp(self):
        self.spec = SlotsSpec.from_grid(_matrix([[1, 2], [3, 4]]))

    def test_shown_as_a_table(self):
        from core.blocks import TableBlock
        blocks = self.spec.display_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertIsInstance(blocks[0], TableBlock)
        self.assertEqual(blocks[0].rows, [["1", "2"], ["3", "4"]])

    def test_cells_have_no_label(self):
        """Подпись ячейке даёт её место; печатать «r1c2» рядом — шум."""
        for field in self.spec.input_fields():
            self.assertEqual(field.label, "")
            self.assertTrue(field.name)

    def test_grid_asks_for_the_grid_widget(self):
        self.assertEqual(resolve_widget(self.spec).name, "grid_fields")
        self.assertIn("grid_fields", [w.name for w in widgets_for(self.spec)])

    def test_plain_slots_still_get_separate_fields(self):
        spec = SlotsSpec(slots=(("a", NumberSpec(value=1)),
                                ("b", NumberSpec(value=2))))
        self.assertEqual(resolve_widget(spec).name, "slot_fields")

    def test_formula_cells_are_not_wrapped_in_dollars(self):
        # В ячейке таблицы «$\\sqrt{2}$» — мусор: доллары нужны печати.
        spec = SlotsSpec.from_grid([[ExpressionSpec(value="sqrt(2)").value]])
        self.assertNotIn("$", spec.display_blocks()[0].rows[0][0])


class ShapeSurvivesSerializationTests(unittest.TestCase):
    """
    Исполнение графа вынесено в отдельный процесс (§9), и задание ездит
    словарём. Потерянная форма означала бы сетку, нарисованную столбиком.
    """

    def test_round_trip(self):
        spec = SlotsSpec.from_grid(_matrix([[1, 2], [3, 4]]))
        restored = AnswerSpec.from_dict(spec.to_dict())
        self.assertEqual(restored.shape, (2, 2))
        self.assertEqual(restored.to_dict(), spec.to_dict())

    def test_unshaped_slots_do_not_carry_an_empty_shape(self):
        spec = SlotsSpec(slots=(("a", NumberSpec(value=1)),))
        self.assertNotIn("shape", spec.to_dict())


class NoAnswerLeaksFromAGridTests(unittest.TestCase):
    """Тот же инвариант, что и у прочих полей: в описании нет ответа."""

    def test_values_are_absent_from_fields(self):
        import json
        spec = SlotsSpec.from_grid(_matrix([[7, 13], [29, 31]]))
        blob = json.dumps([f.to_dict() for f in spec.input_fields()],
                          ensure_ascii=False)
        for value in ("7", "13", "29", "31"):
            self.assertNotIn(value, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
