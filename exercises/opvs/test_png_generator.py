"""
Логическая схема: арность вентилей и корень.

Почему этого теста не хватало. `validate_circuit()` проверяет схему
СИМВОЛЬНО — выполнимость, нетавтологичность, мёртвые входы. Вырожденный
вентиль такую проверку проходит насквозь: sympy сворачивает `And(x)` в
`x`, выражение остаётся корректным, и генератор считает схему валидной.
А на чертеже по ГОСТ 2.743-91 стоит прямоугольник «&» с одним входом —
то есть провод, нарисованный как логический элемент. Символьная проверка
структуру не видит; видит её только проверка арности.

Запуск:
    python -m unittest exercises.opvs.test_png_generator
"""

from __future__ import annotations

import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from exercises.opvs import png_generator as pg  # noqa: E402

# Дефект встречался примерно в 2% вентилей — на одном сиде его можно не
# увидеть вовсе. Поэтому инварианты проверяются на выборке.
SEEDS = range(120)


def _circuits(builder):
    for seed in SEEDS:
        random.seed(seed)
        yield seed, builder()


class ArityTests(unittest.TestCase):
    def test_and_or_gates_have_at_least_two_inputs(self):
        """
        Вентиль «&» или «1» с единственным входом — не логика, а провод.
        Он же добавляет лишний уровень скобок в формулу под схемой.
        """
        for seed, elements in _circuits(pg._build_random_circuit):
            for element in elements:
                if element.type in ("AND", "OR"):
                    with self.subTest(seed=seed, type=element.type):
                        self.assertGreaterEqual(
                            len(element.inputs), 2,
                            "вентиль с одним входом нарисован как элемент")

    def test_not_gates_have_exactly_one_input(self):
        for seed, elements in _circuits(pg._build_random_circuit):
            for element in elements:
                if element.type == "NOT":
                    with self.subTest(seed=seed):
                        self.assertEqual(len(element.inputs), 1)

    def test_inputs_are_leaves(self):
        for seed, elements in _circuits(pg._build_random_circuit):
            for element in elements:
                if element.type == "INPUT":
                    with self.subTest(seed=seed):
                        self.assertEqual(element.inputs, [])


class RootTests(unittest.TestCase):
    """
    Последний элемент списка — выход схемы. На этом держатся и подпись
    формулы (`elements[-1].get_logic_str()`), и верификация
    (`validate_circuit` берёт `elements[-1]` за корень).
    """

    def test_last_element_is_consumed_by_nobody(self):
        for seed, elements in _circuits(pg._build_random_circuit):
            root = elements[-1]
            consumed = {id(i) for e in elements for i in e.inputs}
            with self.subTest(seed=seed):
                self.assertNotIn(id(root), consumed,
                                 "корнем стоит элемент, у которого есть "
                                 "потребитель — формула опишет часть схемы")

    def test_every_element_reaches_the_root(self):
        # Оборванная ветка означала бы нарисованный, но ни на что не
        # влияющий кусок схемы.
        for seed, elements in _circuits(pg._build_random_circuit):
            reached, stack = set(), [elements[-1]]
            while stack:
                node = stack.pop()
                if id(node) in reached:
                    continue
                reached.add(id(node))
                stack.extend(node.inputs)
            with self.subTest(seed=seed):
                self.assertEqual(len(reached), len(elements))

    def test_single_unused_node_becomes_the_output_itself(self):
        """
        Прямая проверка того самого дефекта: когда без потребителя остаётся
        ровно один узел, он и есть выход. Раньше его оборачивали в AND с
        одним входом — отсюда и `((...))` в формуле.
        """
        wrapped = 0
        for _, elements in _circuits(pg._build_random_circuit):
            root = elements[-1]
            if root.type in ("AND", "OR") and len(root.inputs) == 1:
                wrapped += 1
        self.assertEqual(wrapped, 0)


class FormulaTests(unittest.TestCase):
    def test_formula_has_balanced_parentheses(self):
        for seed, elements in _circuits(pg._build_random_circuit):
            text = elements[-1].get_logic_str()
            with self.subTest(seed=seed, formula=text):
                self.assertEqual(text.count("("), text.count(")"))

    def test_formula_mentions_every_input(self):
        for seed, elements in _circuits(pg._build_random_circuit):
            text = elements[-1].get_logic_str()
            for element in elements:
                if element.type == "INPUT":
                    with self.subTest(seed=seed, name=element.name):
                        self.assertIn(element.name, text)


class MakeFunctionTests(unittest.TestCase):
    """Публичный вход: он и попадает в задание."""

    def test_produces_a_valid_circuit_without_degenerate_gates(self):
        for seed in range(20):
            random.seed(seed)
            elements = pg.make_function()
            with self.subTest(seed=seed):
                self.assertTrue(pg.validate_circuit(elements).valid)
                for element in elements:
                    if element.type in ("AND", "OR"):
                        self.assertGreaterEqual(len(element.inputs), 2)


if __name__ == "__main__":
    unittest.main()
