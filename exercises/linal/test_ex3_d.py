"""
Ключ к заданию по 3D-геометрии: пирамида обязана быть пирамидой.

Тест проверяет то, что текстовый ком скрывает по построению: что четыре
точки не лежат в одной плоскости и что величины в ответе не повторяются.
Обе проверки нашли настоящие дефекты — 2% выпусков с нулевым объёмом и
дословный дубль уравнения плоскости.

Запуск:
    python -m unittest exercises.linal.test_ex3_d
"""

from __future__ import annotations

import os
import random
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from exercises.linal import ex3_d  # noqa: E402


def _value(answer: str, prefix: str) -> float:
    for line in answer.split("\n"):
        if line.startswith(prefix):
            return float(line.split(":", 1)[1])
    raise AssertionError(f"в ответе нет строки {prefix!r}:\n{answer}")


class NonDegenerateTests(unittest.TestCase):
    def test_volume_is_never_zero(self):
        """
        Четыре случайные точки в 2% случаев ложились в одну плоскость:
        «найдите объём пирамиды» выдавалось с ответом 0, то есть без
        пирамиды.
        """
        for seed in range(60):
            random.seed(seed)
            _, answer = ex3_d.get_exercise()
            with self.subTest(seed=seed):
                self.assertGreater(_value(answer, "объем пирамиды"), 0)

    def test_areas_are_positive(self):
        for seed in range(30):
            random.seed(seed)
            _, answer = ex3_d.get_exercise()
            for prefix in ("площадь A1-A3-A4", "площадь A2-A3-A4"):
                with self.subTest(seed=seed, prefix=prefix):
                    self.assertGreater(_value(answer, prefix), 0)


class NoDuplicatesTests(unittest.TestCase):
    def test_plane_equation_appears_once(self):
        # Раньше одно и то же уравнение печаталось дважды — как
        # симметричная точка в ex2_d.
        random.seed(1)
        _, answer = ex3_d.get_exercise()
        self.assertEqual(
            sum(1 for line in answer.split("\n")
                if line.startswith("плоскость A2_A3_A4")), 1)


class ShapeTests(unittest.TestCase):
    def test_every_promised_item_is_present(self):
        random.seed(2)
        task, answer = ex3_d.get_exercise()
        for prefix in ("угол A2-A1-A3", "площадь A1-A3-A4", "объем пирамиды",
                       "площадь A2-A3-A4", "плоскость A2_A3_A4",
                       "уравнения A1H", "проекция точки A1",
                       "длина высоты из вершины A2"):
            self.assertIn(prefix, answer)

    def test_statement_gives_four_points(self):
        random.seed(3)
        task, _ = ex3_d.get_exercise()
        self.assertEqual(len(re.findall(r"A\d: \(", task)), 4)


if __name__ == "__main__":
    unittest.main()
