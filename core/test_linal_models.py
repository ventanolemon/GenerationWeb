"""
Геометрия линала как модели: треугольник и пирамида.

Самый грязный материал из четырёх, и проверяется он так же, как в первом
пункте, — АРИФМЕТИКОЙ. Каждая величина пересчитывается здесь независимо от
того, как её считает модель: длины по координатам, площадь по векторному
произведению, объём по смешанному, высоты через `V = S·h/3`. Именно
отсутствие такой проверки позволило неверной высоте (§2.1) прожить в
текстовом коме до июльского разбора.

Отдельно сторожится то, ради чего перевод и делался: величины ТОЧНЫЕ.
Легаси печатает `sqrt(65.0)`, `(-0.0, 4.0)` и
`arccos(-13.0 / 29.068883707497264)`; ни одну из этих строк нельзя ни
проверить, ни переписать в тетрадь.

Запуск:
    python -m unittest core.test_linal_models
"""

from __future__ import annotations

import math
import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sympy as sp  # noqa: E402

from core.equation_text import (  # noqa: E402
    EquationTextError, as_expression, normalise, proportional, same_equation,
)
from core.models.base import ModelConfigError  # noqa: E402
from core.models.linal_pyramid import MODEL as PYRAMID  # noqa: E402
from core.models.linal_triangle import MODEL as TRIANGLE  # noqa: E402

SEEDS = range(20)
X, Y, Z = sp.symbols("x y z")


def _triangle(seed: int, **params):
    return TRIANGLE.build(random.Random(seed), **params)


def _pyramid(seed: int, **params):
    return PYRAMID.build(random.Random(seed), **params)


def _on(line, point, symbols=(X, Y)) -> bool:
    return sp.simplify(line.subs(dict(zip(symbols, list(point))))) == 0


class TriangleArithmeticTests(unittest.TestCase):
    """Каждая величина пересчитана независимо от модели."""

    def test_lengths_match_the_coordinates(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            a1, a2, a3 = values["a1"], values["a2"], values["a3"]
            pairs = (("len_a1a2", a1, a2), ("len_a1a3", a1, a3),
                     ("len_a2a3", a2, a3))
            for name, first, second in pairs:
                with self.subTest(seed=seed, name=name):
                    self.assertAlmostEqual(
                        float(values[name]),
                        math.dist([float(first[0]), float(first[1])],
                                  [float(second[0]), float(second[1])]),
                        places=9)

    def test_area_matches_the_cross_product(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            a1, a2, a3 = values["a1"], values["a2"], values["a3"]
            cross = ((a2[0] - a1[0]) * (a3[1] - a1[1])
                     - (a2[1] - a1[1]) * (a3[0] - a1[0]))
            with self.subTest(seed=seed):
                self.assertEqual(values["area"], sp.Rational(abs(cross), 2))

    def test_height_agrees_with_the_area(self):
        """
        Тот самый инвариант `0.5 · |A1A2| · h = S`, который поймал неверную
        высоту в легаси. Здесь он проверяется СИМВОЛЬНО — величины точные,
        и приближаться не к чему.
        """
        for seed in SEEDS:
            values = _triangle(seed).values
            with self.subTest(seed=seed):
                self.assertEqual(
                    sp.simplify(sp.Rational(1, 2) * values["len_a1a2"]
                                * values["height_length"] - values["area"]), 0)

    def test_height_is_not_the_distance_from_a1(self):
        # Две разные величины из разных пунктов задания. Совпадать могут
        # лишь случайно — у равнобедренного.
        differ = sum(
            1 for seed in SEEDS
            if sp.simplify(_triangle(seed).values["height_length"]
                           - _triangle(seed).values["distance_a1_a2a3"]) != 0)
        self.assertGreater(differ, len(SEEDS) - 3)

    def test_angles_sum_to_pi(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            total = sum(float(values[f"angle_a{i}"]) for i in (1, 2, 3))
            with self.subTest(seed=seed):
                self.assertAlmostEqual(total, math.pi, places=9)

    def test_distance_matches_the_area_of_the_other_side(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            with self.subTest(seed=seed):
                self.assertEqual(
                    sp.simplify(sp.Rational(1, 2) * values["len_a2a3"]
                                * values["distance_a1_a2a3"] - values["area"]),
                    0)


class TriangleGeometryTests(unittest.TestCase):
    def test_every_line_passes_through_its_points(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            cases = (("line_a1a2", ("a1", "a2")), ("line_a1a3", ("a1", "a3")),
                     ("line_a2a3", ("a2", "a3")),
                     ("median_a3", ("a3", "midpoint_a1a2")),
                     ("height_a3", ("a3", "foot_a3")))
            for line, points in cases:
                for name in points:
                    with self.subTest(seed=seed, line=line, point=name):
                        self.assertTrue(_on(values[line], values[name]))

    def test_height_is_perpendicular_to_the_base(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            direction = values["a2"] - values["a1"]
            height = values["foot_a3"] - values["a3"]
            with self.subTest(seed=seed):
                self.assertEqual(sp.simplify(direction.dot(height)), 0)

    def test_median_hits_the_middle(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            with self.subTest(seed=seed):
                self.assertEqual(values["midpoint_a1a2"],
                                 (values["a1"] + values["a2"]) / 2)

    def test_symmetric_point_is_a_mirror_image(self):
        """Середина A1A1′ лежит на A2A3, а отрезок ей перпендикулярен."""
        for seed in SEEDS:
            values = _triangle(seed).values
            middle = (values["a1"] + values["symmetric_a1"]) / 2
            shift = values["symmetric_a1"] - values["a1"]
            side = values["a3"] - values["a2"]
            with self.subTest(seed=seed):
                self.assertTrue(_on(values["line_a2a3"], middle))
                self.assertEqual(sp.simplify(shift.dot(side)), 0)

    def test_triangle_is_not_degenerate(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertGreaterEqual(_triangle(seed).values["area"], 4)


class ExactnessTests(unittest.TestCase):
    """
    Ради чего перевод и делался: в ответе нет плавающей точки.

    `sqrt(65.0)` и `arccos(-13.0 / 29.068883707497264)` — не величины, а
    строки, и именно из-за них ответ невозможно ни проверить, ни списать.
    """

    def test_coordinates_are_integers(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            for name in ("a1", "a2", "a3"):
                with self.subTest(seed=seed, name=name):
                    self.assertTrue(all(c.is_Integer for c in values[name]))

    def test_no_floats_anywhere(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            for name, value in values.items():
                with self.subTest(seed=seed, name=name):
                    self.assertFalse(
                        sp.sympify(value).atoms(sp.Float),
                        f"{name} содержит число с плавающей точкой: {value}")

    def test_line_coefficients_are_coprime_integers(self):
        for seed in SEEDS:
            values = _triangle(seed).values
            for name in ("line_a1a2", "line_a1a3", "line_a2a3"):
                coefficients = sp.Poly(values[name], X, Y).coeffs()
                with self.subTest(seed=seed, name=name):
                    self.assertTrue(all(c.is_Integer for c in coefficients))
                    self.assertEqual(sp.gcd([abs(c) for c in coefficients]), 1)
                    self.assertGreater(coefficients[0], 0)


class TriangleEquivalenceTests(unittest.TestCase):
    def test_a_multiple_of_the_equation_is_the_same_line(self):
        instance = _triangle(1)
        for factor in (2, -1, sp.Rational(1, 3)):
            with self.subTest(factor=factor):
                self.assertTrue(instance.equivalent(
                    "line_a1a2", factor * instance.values["line_a1a2"]))

    def test_a_different_line_is_refused(self):
        instance = _triangle(1)
        self.assertFalse(instance.equivalent("line_a1a2",
                                             instance.values["line_a2a3"]))

    def test_the_text_form_is_accepted(self):
        instance = _triangle(1)
        text = f"{instance.values['median_a3']} = 0"
        self.assertTrue(instance.equivalent("median_a3", text))

    def test_non_equation_values_use_the_default_rule(self):
        instance = _triangle(1)
        self.assertTrue(instance.equivalent("area", instance.values["area"]))
        self.assertFalse(instance.equivalent("area",
                                             instance.values["area"] + 1))


class TriangleParamTests(unittest.TestCase):
    def test_coordinates_stay_inside_the_range(self):
        for seed in SEEDS:
            values = _triangle(seed, min=0, max=9).values
            for name in ("a1", "a2", "a3"):
                with self.subTest(seed=seed, name=name):
                    self.assertTrue(all(0 <= c <= 9 for c in values[name]))

    def test_min_area_is_honoured(self):
        for seed in range(8):
            self.assertGreaterEqual(_triangle(seed, min_area=12).values["area"],
                                    12)

    def test_narrow_range_is_a_config_error(self):
        with self.assertRaises(ModelConfigError):
            _triangle(0, min=0, max=2)

    def test_reproducible_from_the_seed(self):
        self.assertEqual(_triangle(9).values["a1"], _triangle(9).values["a1"])


class PyramidTests(unittest.TestCase):
    def test_volume_matches_the_mixed_product(self):
        for seed in SEEDS:
            values = _pyramid(seed).values
            a1, a2, a3, a4 = (values["a1"], values["a2"],
                              values["a3"], values["a4"])
            mixed = (a2 - a1).dot((a3 - a1).cross(a4 - a1))
            with self.subTest(seed=seed):
                self.assertEqual(values["volume"], sp.Rational(abs(mixed), 6))

    def test_volume_agrees_with_both_heights(self):
        """
        `V = S·h/3` для ДВУХ разных граней — перекрёстная проверка, которая
        сходится только если верны и площади, и высоты.
        """
        for seed in SEEDS:
            values = _pyramid(seed).values
            for area, height in (("area_a2a3a4", "height_a1"),
                                 ("area_a1a3a4", "height_a2")):
                with self.subTest(seed=seed, area=area):
                    self.assertEqual(
                        sp.simplify(sp.Rational(1, 3) * values[area]
                                    * values[height] - values["volume"]), 0)

    def test_plane_passes_through_its_three_points(self):
        for seed in SEEDS:
            values = _pyramid(seed).values
            for name in ("a2", "a3", "a4"):
                with self.subTest(seed=seed, point=name):
                    self.assertTrue(_on(values["plane_a2a3a4"], values[name],
                                        (X, Y, Z)))

    def test_the_apex_is_off_the_opposite_face(self):
        # Иначе пирамиды нет: четыре точки в одной плоскости.
        for seed in SEEDS:
            values = _pyramid(seed).values
            with self.subTest(seed=seed):
                self.assertFalse(_on(values["plane_a2a3a4"], values["a1"],
                                     (X, Y, Z)))

    def test_projection_lies_on_the_face_and_gives_the_height(self):
        for seed in SEEDS:
            values = _pyramid(seed).values
            projection = values["projection_a1"]
            with self.subTest(seed=seed):
                self.assertTrue(_on(values["plane_a2a3a4"], projection,
                                    (X, Y, Z)))
                self.assertEqual(
                    sp.simplify(sp.sqrt(sum((values["a1"][i] - projection[i]) ** 2
                                            for i in range(3)))
                                - values["height_a1"]), 0)

    def test_normal_is_perpendicular_to_the_face(self):
        for seed in SEEDS:
            values = _pyramid(seed).values
            normal = values["normal_a1"]
            for edge in (values["a3"] - values["a2"], values["a4"] - values["a2"]):
                with self.subTest(seed=seed):
                    self.assertEqual(sp.simplify(normal.dot(edge)), 0)

    def test_normal_coordinates_are_coprime_integers(self):
        for seed in SEEDS:
            normal = _pyramid(seed).values["normal_a1"]
            with self.subTest(seed=seed):
                self.assertTrue(all(c.is_Integer for c in normal))
                self.assertEqual(sp.gcd([abs(c) for c in normal]), 1)

    def test_min_volume_is_honoured(self):
        for seed in range(8):
            self.assertGreaterEqual(_pyramid(seed, min_volume=6).values["volume"],
                                    6)

    def test_plane_equivalence_is_up_to_a_factor(self):
        instance = _pyramid(2)
        self.assertTrue(instance.equivalent(
            "plane_a2a3a4", -3 * instance.values["plane_a2a3a4"]))
        self.assertFalse(instance.equivalent(
            "plane_a2a3a4", instance.values["plane_a1a3a4"]))

    def test_narrow_range_is_a_config_error(self):
        with self.assertRaises(ModelConfigError):
            _pyramid(0, min=0, max=1)


class EquationTextTests(unittest.TestCase):
    VARS = ("x", "y")

    def test_the_same_line_written_three_ways(self):
        base = as_expression("3x + 2y - 5", self.VARS)
        for text in ("3x + 2y - 5 = 0", "6x + 4y = 10", "-3x - 2y + 5 = 0",
                     "3*x + 2*y = 5"):
            with self.subTest(text=text):
                self.assertTrue(same_equation(base, text, self.VARS))

    def test_a_different_line_is_refused(self):
        base = as_expression("3x + 2y - 5", self.VARS)
        for text in ("2x + 3y - 5 = 0", "3x + 2y - 6 = 0", "x = 0"):
            with self.subTest(text=text):
                self.assertFalse(same_equation(base, text, self.VARS))

    def test_the_trivial_equation_is_not_a_line(self):
        # `0 = 0` выполняется везде и множества не задаёт.
        self.assertFalse(proportional(sp.Integer(0), sp.Integer(0), self.VARS))

    def test_unknown_name_is_named(self):
        with self.assertRaises(EquationTextError) as ctx:
            as_expression("3x + 2z", self.VARS)
        self.assertIn("z", str(ctx.exception))

    def test_nothing_is_executed(self):
        for text in ("__import__('os')", "x.__class__"):
            with self.subTest(text=text), self.assertRaises(EquationTextError):
                as_expression(text, self.VARS)

    def test_two_equal_signs_are_refused(self):
        with self.assertRaises(EquationTextError):
            as_expression("x = y = 0", self.VARS)

    def test_normalise_gives_coprime_integers(self):
        self.assertEqual(normalise(as_expression("-6x - 4y + 10", self.VARS),
                                   self.VARS),
                         sp.sympify("3*x + 2*y - 5"))


class EquationSpecTests(unittest.TestCase):
    VALUE = "3*x + 2*y - 5 = 0"
    VARS = ("x", "y")

    def _spec(self, mode=None):
        from core.answers import EquationSpec

        if mode is None:
            return EquationSpec(value=self.VALUE, variables=self.VARS)
        return EquationSpec(value=self.VALUE, variables=self.VARS, mode=mode)

    def test_proportional_answers_are_accepted(self):
        for text in ("6x + 4y = 10", "-3x - 2y + 5 = 0", "3x+2y-5=0"):
            with self.subTest(text=text):
                self.assertTrue(self._spec().check(text).accepted)

    def test_strict_demands_the_canonical_form(self):
        from core.answers import CheckMode, Reason

        spec = self._spec(CheckMode.STRICT)
        verdict = spec.check("6x + 4y - 10 = 0")
        self.assertFalse(verdict.accepted)
        self.assertIs(verdict.reason, Reason.WRONG_FORM)
        self.assertTrue(spec.check("3x + 2y - 5 = 0").accepted)

    def test_examples_show_that_scaling_is_accepted(self):
        """
        Второй пример здесь не для полноты: без него механизм выглядит
        строже, чем он есть, и его выключают.
        """
        examples = self._spec().accepted_examples()
        self.assertEqual(len(examples), 2)
        for text in examples:
            self.assertTrue(self._spec().check(text).accepted)

    def test_distractors_are_all_wrong(self):
        spec = self._spec()
        wrong = spec.distractors(3)
        self.assertTrue(wrong)
        for text in wrong:
            self.assertFalse(spec.check(text).accepted, text)

    def test_unparsed_and_empty_are_distinguished(self):
        from core.answers import Reason

        self.assertIs(self._spec().check("хрю").reason, Reason.UNPARSED)
        self.assertIs(self._spec().check("  ").reason, Reason.EMPTY)

    def test_survives_serialisation(self):
        from core.answers import AnswerSpec

        spec = self._spec()
        self.assertEqual(AnswerSpec.from_dict(spec.to_dict()), spec)

    def test_the_answer_does_not_leak_into_the_field(self):
        field = self._spec().input_fields()[0]
        self.assertNotIn("5", field.hint)
        self.assertIn("x", field.hint)


class TriangleTaskTests(unittest.TestCase):
    """Одна модель — разные задания, и все проверяемы."""

    @staticmethod
    def _run(port: str, slot: str):
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec

        graph = {"nodes": [
            {"id": "m", "type": "model_linal_triangle", "params": {}},
            {"id": "t", "type": "task",
             "params": {"statement": "Найдите.", "slots": [slot]}},
        ], "edges": [{"from": port, "to": "t:ответ"}]}
        return GraphExecutor(GraphSpec.parse(graph)).run()

    def _accepts_its_own_example(self, port, slot):
        from core.interactive import session_from_task

        task = self._run(port, slot)
        self.assertTrue(task.is_checkable)
        example = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(example).correct)
        return task

    def test_find_the_vertex(self):
        task = self._accepts_its_own_example("m:a3", "ответ:matrix")
        self.assertEqual(len(task.answer_spec.input_fields()), 2)

    def test_find_the_area(self):
        self._accepts_its_own_example("m:area", "ответ:expr")

    def test_write_the_line_equation(self):
        task = self._accepts_its_own_example("m:line_a1a2",
                                             "ответ:equation:vars=x,y")
        self.assertEqual(task.answer_spec.kind, "equation")

    def test_scaled_equation_is_accepted_end_to_end(self):
        from core.interactive import session_from_task

        task = self._run("m:median_a3", "ответ:equation:vars=x,y")
        doubled = task.answer_spec.accepted_examples()[1]
        self.assertTrue(session_from_task(task).submit(doubled).correct)

    def test_exact_length_with_a_root(self):
        task = self._run("m:len_a1a2", "ответ:expr")
        self.assertNotIn(".", task.answer_spec.value,
                         "длина уехала в ответ числом с плавающей точкой")

    def test_pyramid_plane_task(self):
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec
        from core.interactive import session_from_task

        graph = {"nodes": [
            {"id": "m", "type": "model_linal_pyramid", "params": {}},
            {"id": "t", "type": "task", "params": {
                "statement": "Выпишите уравнение плоскости A2A3A4.",
                "slots": ["ответ:equation:vars=x,y,z"]}},
        ], "edges": [{"from": "m:plane_a2a3a4", "to": "t:ответ"}]}
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        example = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(example).correct)


if __name__ == "__main__":
    unittest.main()
