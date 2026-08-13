"""
Модель: треугольник на плоскости.

Четвёртый пункт плана (§5) и самый грязный материал из четырёх. Здесь
живёт тот самый текстовый ком, с которого весь разбор начался: двенадцать
величин, склеенных в строку, из которой нельзя спросить ни одну по
отдельности, и в которой полгода жила неверная высота (§2.1).

Что даёт перевод на стандарт, кроме адресуемости величин:

* **точность вместо плавающей точки**. Легаси считает во float и печатает
  `sqrt(65.0)`, `(-0.0, 4.0)` и `arccos(-13.0 / 29.068883707497264)` —
  ответ-формулу со мусором внутри. Здесь всё точное: длина `sqrt(65)`,
  площадь `13/2`, угол `acos(-13*sqrt(58)/116)`;
* **уравнения — величины, а не строки**. Легаси печатает
  `(-7)x + (4)y + (-16) = 0` текстом; здесь это выражение sympy, и ответ
  студента сравнивается с ним по существу — с точностью до множителя
  (`core/equation_text.py`), потому что `6x + 4y - 10 = 0` и
  `3x + 2y - 5 = 0` это одна прямая.

Каким заданием станут величины, решает разводка: «найдите A3» по двум
данным прямым, «найдите площадь», «выпишите уравнение медианы»,
«постройте точку, симметричную A1» — всё это одна модель.
"""

from __future__ import annotations

from .base import Instance, Model, ModelConfigError, ModelError, Output

#: Величины-уравнения: ответ на них сравнивается с точностью до множителя.
_EQUATIONS = ("line_a1a2", "line_a1a3", "line_a2a3", "median_a3", "height_a3")

VARIABLES = ("x", "y")


class TriangleInstance(Instance):
    """Экземпляр, знающий, что уравнение задаёт множество, а не выражение."""

    def equivalent(self, name: str, answer) -> bool:
        if name not in _EQUATIONS:
            return super().equivalent(name, answer)
        from ..equation_text import same_equation

        return same_equation(self.values[name], answer, VARIABLES)


class TriangleModel(Model):
    """Треугольник с целыми вершинами и точными величинами."""

    name = "linal_triangle"
    title = "Треугольник на плоскости"
    description = (
        "Треугольник с целыми вершинами: стороны, углы, площадь, "
        "уравнения сторон, медианы и высоты, расстояние от вершины до "
        "противоположной стороны, симметричная точка. Всё точное — без "
        "плавающей точки в ответе."
    )
    category = "linalg"

    OUTPUTS = [
        Output("a1", "matrix", "A1", "Первая вершина, столбец 2×1."),
        Output("a2", "matrix", "A2", "Вторая вершина."),
        Output("a3", "matrix", "A3", "Третья вершина."),
        Output("line_a1a2", "expr", "Прямая A1A2",
               "Выражение, равное нулю на прямой."),
        Output("line_a1a3", "expr", "Прямая A1A3", ""),
        Output("line_a2a3", "expr", "Прямая A2A3", ""),
        Output("median_a3", "expr", "Медиана из A3",
               "Прямая через A3 и середину A1A2."),
        Output("height_a3", "expr", "Высота из A3",
               "Прямая через A3 перпендикулярно A1A2."),
        Output("len_a1a2", "expr", "|A1A2|", "Точная длина, обычно с корнем."),
        Output("len_a1a3", "expr", "|A1A3|", ""),
        Output("len_a2a3", "expr", "|A2A3|", ""),
        Output("angle_a1", "expr", "Угол при A1", "В радианах, точный."),
        Output("angle_a2", "expr", "Угол при A2", ""),
        Output("angle_a3", "expr", "Угол при A3", ""),
        Output("area", "expr", "Площадь", "Точная, рациональная."),
        Output("height_length", "expr", "Длина высоты из A3", ""),
        Output("distance_a1_a2a3", "expr", "Расстояние от A1 до A2A3", ""),
        Output("midpoint_a1a2", "matrix", "Середина A1A2", ""),
        Output("foot_a3", "matrix", "Основание высоты из A3", ""),
        Output("symmetric_a1", "matrix", "A1′",
               "Точка, симметричная A1 относительно A2A3."),
    ]

    PARAMS = {
        "min": {"type": "int", "default": -6},
        "max": {"type": "int", "default": 8, "optional": True},
        "min_area": {"type": "int", "default": 4, "optional": True},
    }

    def normalize_params(self, params: dict) -> dict:
        def whole(key, default):
            try:
                return int(params.get(key, default))
            except (TypeError, ValueError):
                raise ModelConfigError(f"{key} должно быть целым числом.")

        low, high = whole("min", -6), whole("max", 8)
        if high - low < 4:
            raise ModelConfigError(
                "диапазон координат слишком узкий: в нём не разместить "
                "невырожденный треугольник.")
        area = whole("min_area", 4)
        if area < 1:
            raise ModelConfigError("min_area должна быть положительной.")
        return {"min": low, "max": high, "min_area": area}

    def build(self, rng, **params) -> Instance:
        import sympy as sp

        cfg = self.normalize_params(params)
        x, y = sp.symbols("x y")

        for _ in range(400):
            points = [sp.Matrix([rng.randint(cfg["min"], cfg["max"]),
                                 rng.randint(cfg["min"], cfg["max"])])
                      for _ in range(3)]
            a1, a2, a3 = points
            cross = _cross(a2 - a1, a3 - a1)
            # Площадь заодно и проверяет невырожденность: у трёх точек на
            # одной прямой она равна нулю. Нижняя граница отсекает
            # «иголки», где чертёж нечитаем, а высота почти совпадает со
            # стороной.
            if abs(cross) < 2 * cfg["min_area"]:
                continue

            line12 = _line(a1, a2, x, y)
            line13 = _line(a1, a3, x, y)
            line23 = _line(a2, a3, x, y)
            middle = (a1 + a2) / 2
            foot = _foot(a3, a1, a2)

            return TriangleInstance(
                values={
                    "a1": a1, "a2": a2, "a3": a3,
                    "line_a1a2": line12,
                    "line_a1a3": line13,
                    "line_a2a3": line23,
                    "median_a3": _line(a3, middle, x, y),
                    "height_a3": _line(a3, foot, x, y),
                    "len_a1a2": _length(a2 - a1),
                    "len_a1a3": _length(a3 - a1),
                    "len_a2a3": _length(a3 - a2),
                    "angle_a1": _angle(a2 - a1, a3 - a1),
                    "angle_a2": _angle(a1 - a2, a3 - a2),
                    "angle_a3": _angle(a1 - a3, a2 - a3),
                    "area": sp.Rational(abs(cross), 2),
                    "height_length": _length(a3 - foot),
                    "distance_a1_a2a3": _distance(a1, a2, a3),
                    "midpoint_a1a2": middle,
                    "foot_a3": foot,
                    "symmetric_a1": 2 * _foot(a1, a2, a3) - a1,
                },
                params=dict(cfg),
            )
        raise ModelError(
            "не удалось подобрать треугольник в заданных границах — "
            "расширьте диапазон координат или уменьшите min_area.")


def _cross(first, second):
    """Векторное произведение двух плоских векторов — число."""
    return first[0] * second[1] - first[1] * second[0]


def _length(vector):
    import sympy as sp

    return sp.sqrt(vector[0] ** 2 + vector[1] ** 2)


def _angle(first, second):
    """
    Угол между векторами — ТОЧНЫЙ, через acos от рационализованного
    косинуса. Легаси считает во float и печатает
    `arccos(-13.0 / 29.068883707497264)`; такой «ответ» нельзя ни
    проверить, ни переписать в тетрадь.
    """
    import sympy as sp

    dot = first.dot(second)
    norms = _length(first) * _length(second)
    return sp.acos(sp.radsimp(dot / norms))


def _line(point, other, x, y):
    """
    Уравнение прямой через две точки, приведённое к целым коэффициентам.

    Каноническая форма нужна показу, а не проверке: сравнение всё равно
    идёт по пропорциональности, но ключ с `-6x - 4y + 10 = 0` там, где
    достаточно `3x + 2y - 5 = 0`, заставляет сверять руками.
    """
    from ..equation_text import normalise

    direction = other - point
    expr = direction[1] * (x - point[0]) - direction[0] * (y - point[1])
    return normalise(expr, ("x", "y"))


def _foot(point, first, second):
    """Основание перпендикуляра из `point` на прямую (first, second)."""
    import sympy as sp

    direction = second - first
    t = (point - first).dot(direction) / direction.dot(direction)
    return sp.Matrix(first + t * direction)


def _distance(point, first, second):
    """Расстояние от точки до прямой — точное, через площадь."""
    import sympy as sp

    direction = second - first
    return sp.Abs(_cross(direction, point - first)) / _length(direction)


MODEL = TriangleModel()
