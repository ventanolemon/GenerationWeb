"""
Три доработки языка Июль: веса выбора, многовходовая арифметика, логарифм.

Все три взяты из списка пожеланий, сверенного с реестром
(`docs/architecture/july_language_wishlist.md`), — это те пункты, которых
действительно не было.

Проверяем не «узел работает», а решения, которые в них заложены:

  * веса нормируются узлом, потому что требовать долей значит заставлять
    автора пересчитывать их при каждом новом варианте;
  * многовходовыми стали ТОЛЬКО сложение и умножение: деление двух
    выражений — это дробь, а «дробь из трёх» многоэтажная и читается
    хуже двух обычных;
  * основание логарифма — полноправный вход, а не текст внутри
    выражения: иначе его нельзя ни сгенерировать случайно, ни
    переиспользовать.
"""

from __future__ import annotations

import collections
import random
import unittest

from core.graph.errors import GraphValidationError
from core.graph.node import ExecContext
from core.graph.nodes import DEFAULT_REGISTRY


def _ctx(seed: int = 0) -> ExecContext:
    return ExecContext(rng=random.Random(seed))


def _make(type_id: str, params: dict):
    return DEFAULT_REGISTRY.create(type_id, "n", params)


# ======================================================================
#  Веса случайного выбора
# ======================================================================

class WeightedChoiceTests(unittest.TestCase):

    def _distribution(self, params: dict, runs: int = 3000) -> dict:
        node = _make("random_choice", params)
        counter: collections.Counter = collections.Counter()
        for seed in range(runs):
            counter[node.compute({}, _ctx(seed))["out"]] += 1
        return {key: value / runs for key, value in counter.items()}

    def test_weights_shift_the_distribution(self):
        got = self._distribution(
            {"items": ["ln", "arctg", "sqrt"], "weights": [7, 2, 1]})
        self.assertAlmostEqual(got["ln"], 0.7, delta=0.05)
        self.assertAlmostEqual(got["arctg"], 0.2, delta=0.05)
        self.assertAlmostEqual(got["sqrt"], 0.1, delta=0.05)

    def test_weights_need_not_sum_to_one(self):
        """
        Узел нормирует сам. Иначе автор пересчитывал бы доли при каждом
        добавлении варианта — ровно та арифметика, которую машина делает
        лучше и не забывает.
        """
        got = self._distribution({"items": ["a", "b"], "weights": [3, 1]})
        self.assertAlmostEqual(got["a"], 0.75, delta=0.05)

    def test_zero_weight_never_wins(self):
        got = self._distribution({"items": ["a", "b"], "weights": [0, 1]},
                                 runs=500)
        self.assertNotIn("a", got)

    def test_no_weights_is_uniform(self):
        got = self._distribution({"items": ["a", "b", "c"]})
        for key in "abc":
            self.assertAlmostEqual(got[key], 1 / 3, delta=0.05)

    def test_weights_can_come_from_a_wire(self):
        """
        Ради чего вход и заведён: несколько выборов можно сделать
        зависимыми от одного параметра генерации — посчитал веса один
        раз и раздал проводами.
        """
        node = _make("random_choice", {"items": ["a", "b"]})
        counter: collections.Counter = collections.Counter()
        for seed in range(600):
            counter[node.compute({"weights": [9, 1]}, _ctx(seed))["out"]] += 1
        self.assertGreater(counter["a"] / 600, 0.8)

    def test_wire_overrides_the_parameter(self):
        node = _make("random_choice", {"items": ["a", "b"], "weights": [1, 0]})
        seen = {node.compute({"weights": [0, 1]}, _ctx(s))["out"]
                for s in range(50)}
        self.assertEqual(seen, {"b"})

    def test_weighted_draw_without_replacement(self):
        """
        При выборе нескольких без повторов вес означает шанс на ПЕРВОМ
        шаге: выбранный вариант убирается, и распределение считается
        заново по остатку. Другого смысла у весов без возвращения нет.
        """
        node = _make("random_choice",
                     {"items": ["a", "b", "c"], "weights": [10, 1, 1],
                      "count": 2, "elem_type": "string"})
        for seed in range(20):
            chosen = node.compute({}, _ctx(seed))["out"]
            self.assertEqual(len(chosen), len(set(chosen)))

    # ---------- отказы ----------

    def test_length_mismatch_is_refused(self):
        with self.assertRaises(GraphValidationError):
            _make("random_choice", {"items": ["a", "b"], "weights": [1]})

    def test_negative_weight_is_refused(self):
        with self.assertRaises(GraphValidationError):
            _make("random_choice", {"items": ["a", "b"], "weights": [-1, 2]})

    def test_all_zero_is_refused(self):
        with self.assertRaises(GraphValidationError):
            _make("random_choice", {"items": ["a", "b"], "weights": [0, 0]})

    def test_non_numeric_weight_is_refused(self):
        with self.assertRaises(GraphValidationError):
            _make("random_choice", {"items": ["a", "b"], "weights": ["мн", "1"]})


# ======================================================================
#  Многовходовая арифметика
# ======================================================================

class VariadicArithmeticTests(unittest.TestCase):

    def _sum(self, count: int, values):
        node = _make("expr_binop", {"op": "add", "count": count})
        inputs = {chr(ord("a") + i): v for i, v in enumerate(values)}
        return node.compute(inputs, _ctx())["out"]

    def test_sum_of_four(self):
        self.assertEqual(self._sum(4, [1, 2, 3, 4]), 10)

    def test_product_of_three(self):
        node = _make("expr_binop", {"op": "mul", "count": 3})
        self.assertEqual(
            node.compute({"a": 2, "b": 3, "c": 5}, _ctx())["out"], 30)

    def test_ports_are_named_a_b_c(self):
        node = _make("expr_binop", {"op": "add", "count": 3})
        self.assertEqual([p.name for p in node.input_ports()], ["a", "b", "c"])

    def test_saved_two_input_graphs_are_untouched(self):
        """
        Имена «a» и «b» сохранены нарочно: провода в уже сохранённых
        графах ссылаются на них, и переименование сломало бы их молча.
        """
        node = _make("expr_binop", {"op": "div"})
        self.assertEqual([p.name for p in node.input_ports()], ["a", "b"])

    def test_division_stays_binary(self):
        """
        Деление двух выражений — это дробь, самая читаемая форма записи.
        «Дробь из трёх» становится многоэтажной и читается хуже двух
        обычных, поэтому третий вход у неё запрещён, а не разрешён молча.
        """
        with self.assertRaises(GraphValidationError):
            _make("expr_binop", {"op": "div", "count": 3})

    def test_power_and_subtraction_stay_binary(self):
        # Степень правоассоциативна, вычитание — лево-; порядок пришлось
        # бы либо показывать на узле, либо выбрать за автора молча.
        for op in ("pow", "sub"):
            with self.subTest(op=op):
                with self.assertRaises(GraphValidationError):
                    _make("expr_binop", {"op": op, "count": 3})

    def test_one_input_is_refused(self):
        with self.assertRaises(GraphValidationError):
            _make("expr_binop", {"op": "add", "count": 1})

    def test_summary_shows_the_arity(self):
        self.assertEqual(_make("expr_binop", {"op": "add"}).summary(), "+")
        self.assertEqual(
            _make("expr_binop", {"op": "add", "count": 3}).summary(), "+ ×3")


# ======================================================================
#  Логарифм с основанием
# ======================================================================

class LogarithmTests(unittest.TestCase):

    def setUp(self):
        import sympy
        self.sympy = sympy
        self.x = sympy.Symbol("x")

    def test_natural_by_default(self):
        node = _make("expr_log", {})
        self.assertEqual(node.compute({"in": self.x}, _ctx())["out"],
                         self.sympy.log(self.x))

    def test_base_from_the_parameter(self):
        node = _make("expr_log", {"base": "2"})
        got = node.compute({"in": 8}, _ctx())["out"]
        self.assertEqual(self.sympy.simplify(got - 3), 0)

    def test_base_from_a_wire(self):
        """
        Ради чего узел и заведён: основание бывает результатом другого
        узла — случайным, параметром задания, вычисленным. Внутри текста
        выражения оно перестаёт быть точкой графа.
        """
        node = _make("expr_log", {})
        got = node.compute({"in": 81, "base": 3}, _ctx())["out"]
        self.assertEqual(self.sympy.simplify(got - 4), 0)

    def test_wire_overrides_the_parameter(self):
        node = _make("expr_log", {"base": "10"})
        got = node.compute({"in": 8, "base": 2}, _ctx())["out"]
        self.assertEqual(self.sympy.simplify(got - 3), 0)

    def test_summary_shows_the_base(self):
        self.assertEqual(_make("expr_log", {}).summary(), "ln")
        self.assertEqual(_make("expr_log", {"base": "3"}).summary(), "log_3")


class RegisteredInTheCatalogTests(unittest.TestCase):
    """Новый узел бесполезен, пока его нет в палитре."""

    def test_log_is_registered_with_a_description(self):
        self.assertTrue(DEFAULT_REGISTRY.has("expr_log"))
        self.assertTrue(DEFAULT_REGISTRY.get("expr_log").description)

    def test_palette_reports_the_new_node(self):
        names = {entry["type_id"] for entry in DEFAULT_REGISTRY.palette()}
        self.assertIn("expr_log", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
