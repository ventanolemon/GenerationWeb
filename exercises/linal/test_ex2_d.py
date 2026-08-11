"""
Ключ к заданию по 2D-геометрии: величины должны сходиться между собой.

Тест проверяет не «функция вернула строку», а АРИФМЕТИКУ ответа. Именно
её отсутствие позволило дефекту жить: в текстовом коме из двенадцати
величин строка «длина высоты» печатала расстояние из другого пункта
задания (2.5495 вместо 7.2111 на одном из треугольников), и заметить это
можно было только пересчитав ответ руками.

Запуск:
    python -m unittest exercises.linal.test_ex2_d
"""

from __future__ import annotations

import math
import os
import random
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from exercises.linal import ex2_d  # noqa: E402


def _number(text: str) -> float:
    """`sqrt(x)` или обычное число → float. Так печатает ключ."""
    text = text.strip().rstrip(",")
    m = re.fullmatch(r"sqrt\(([-\d.eE+]+)\)", text)
    return math.sqrt(float(m.group(1))) if m else float(text)


def _value(answer: str, prefix: str) -> float:
    """Число из строки ответа, начинающейся с `prefix`."""
    for line in answer.split("\n"):
        if line.startswith(prefix):
            return _number(line.split(":", 1)[1])
    raise AssertionError(f"в ответе нет строки {prefix!r}:\n{answer}")


def _side(answer: str, name: str) -> float:
    """
    Длина стороны из строки «длины A1A2: …, A1A3: …, A2A3: …».

    Ищем по имени регулярным выражением, а не разбором по запятым: метка
    и значение разделены тем же двоеточием, что и заголовок строки.
    """
    m = re.search(rf"{name}: (sqrt\([-\d.eE+]+\)|[-\d.eE+]+)", answer)
    if not m:
        raise AssertionError(f"в ответе нет длины {name!r}:\n{answer}")
    return _number(m.group(1))


class AnswerConsistencyTests(unittest.TestCase):
    def test_height_agrees_with_the_area(self):
        """
        Ключевой инвариант: 0.5 · |A1A2| · h = S.

        Он и ловит подмену — у неверной величины (расстояния из пункта 3)
        произведение с площадью не сходится.
        """
        for seed in range(30):
            random.seed(seed)
            _, answer = ex2_d.get_exercise()
            with self.subTest(seed=seed):
                area = _value(answer, "площадь треугольника")
                height = _value(answer, "длина высоты из A3")
                base = _side(answer, "A1A2")
                self.assertAlmostEqual(0.5 * base * height, area, places=6,
                                       msg="высота не сходится с площадью")

    def test_height_is_not_the_distance_from_a1(self):
        """
        Прямая проверка того самого дефекта: две величины — разные пункты
        задания, и совпадать они могут лишь случайно (у равнобедренного).
        """
        differ = 0
        for seed in range(30):
            random.seed(seed)
            _, answer = ex2_d.get_exercise()
            height = _value(answer, "длина высоты из A3")
            distance = _value(answer, "расстояние от A1 до A2A3")
            if abs(height - distance) > 1e-9:
                differ += 1
        self.assertGreater(differ, 25,
                           "высота почти всегда совпадает с расстоянием — "
                           "похоже, печатается одна и та же величина")


class NoDuplicatesTests(unittest.TestCase):
    def test_symmetric_point_appears_once(self):
        # Раньше один и тот же вызов выводился дважды под разными именами.
        random.seed(1)
        _, answer = ex2_d.get_exercise()
        self.assertEqual(
            sum(1 for line in answer.split("\n") if "симметричн" in line), 1)


class ShapeTests(unittest.TestCase):
    def test_every_promised_item_is_present(self):
        random.seed(3)
        _, answer = ex2_d.get_exercise()
        for prefix in ("координаты точки С", "длины A1A2", "площадь треугольника",
                       "длина высоты из A3", "расстояние от A1 до A2A3"):
            self.assertIn(prefix, answer)


if __name__ == "__main__":
    unittest.main()
