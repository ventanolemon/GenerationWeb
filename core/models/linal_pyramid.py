"""
Модель: пирамида в пространстве.

Трёхмерная половина четвёртого пункта (§5) — то, что в легаси называется
`ex3_d`. Устроена так же, как треугольник, и намеренно: если стандарт
описывает общее, то переход из плоскости в пространство не должен требовать
ничего, кроме новых величин.

Что чинится переводом, помимо адресуемости:

* **вырожденная пирамида**. Четыре случайные точки в 2% случаев ложатся в
  одну плоскость, и «найдите объём пирамиды» выдавалось с ответом 0
  (§2.8). Здесь объём задан снизу параметром: конструируем так, чтобы
  свойство выполнялось;
* **точность**. Легаси печатает объём как `4.833333333333333`, а угол —
  как `arccos(-13.0 / 29.068883707497264)`. Здесь объём `29/6`, угол
  `acos(...)` с точным аргументом;
* **уравнение плоскости — величина**, и ответ на него сравнивается с
  точностью до множителя: `2x - y + 3z - 4 = 0` и `4x - 2y + 6z - 8 = 0`
  задают одну плоскость.
"""

from __future__ import annotations

from .base import Instance, Model, ModelConfigError, ModelError, Output

VARIABLES = ("x", "y", "z")

#: Величины-уравнения: сравниваются с точностью до множителя.
_EQUATIONS = ("plane_a2a3a4", "plane_a1a3a4")


class PyramidInstance(Instance):
    """Экземпляр, знающий, что уравнение плоскости задаёт множество."""

    def equivalent(self, name: str, answer) -> bool:
        if name not in _EQUATIONS:
            return super().equivalent(name, answer)
        from ..equation_text import same_equation

        return same_equation(self.values[name], answer, VARIABLES)


class PyramidModel(Model):
    """Пирамида с целыми вершинами и точными величинами."""

    name = "linal_pyramid"
    title = "Пирамида в пространстве"
    description = (
        "Пирамида A1A2A3A4 с целыми вершинами: плоские углы при вершине, "
        "площади граней, объём, уравнения плоскостей, проекция вершины на "
        "грань и высоты. Всё точное; вырожденная пирамида исключена "
        "построением."
    )
    category = "linalg"

    OUTPUTS = [
        Output("a1", "matrix", "A1", "Вершина, столбец 3×1."),
        Output("a2", "matrix", "A2", ""),
        Output("a3", "matrix", "A3", ""),
        Output("a4", "matrix", "A4", ""),
        Output("angle_a2a1a3", "expr", "Угол A2-A1-A3", "В радианах, точный."),
        Output("angle_a2a1a4", "expr", "Угол A2-A1-A4", ""),
        Output("angle_a3a1a4", "expr", "Угол A3-A1-A4", ""),
        Output("area_a1a3a4", "expr", "Площадь A1A3A4", ""),
        Output("area_a2a3a4", "expr", "Площадь A2A3A4", ""),
        Output("volume", "expr", "Объём пирамиды", "Точный, рациональный."),
        Output("plane_a2a3a4", "expr", "Плоскость A2A3A4",
               "Выражение, равное нулю на плоскости."),
        Output("plane_a1a3a4", "expr", "Плоскость A1A3A4", ""),
        Output("normal_a1", "matrix", "Направляющий вектор нормали из A1",
               "Прямая A1H задаётся точкой A1 и этим вектором."),
        Output("projection_a1", "matrix", "Проекция A1 на A2A3A4", ""),
        Output("height_a1", "expr", "Высота из A1", "Расстояние до A2A3A4."),
        Output("height_a2", "expr", "Высота из A2", "Расстояние до A1A3A4."),
    ]

    PARAMS = {
        "min": {"type": "int", "default": -4},
        "max": {"type": "int", "default": 5, "optional": True},
        "min_volume": {"type": "int", "default": 2, "optional": True},
    }

    def normalize_params(self, params: dict) -> dict:
        def whole(key, default):
            try:
                return int(params.get(key, default))
            except (TypeError, ValueError):
                raise ModelConfigError(f"{key} должно быть целым числом.")

        low, high = whole("min", -4), whole("max", 5)
        if high - low < 3:
            raise ModelConfigError(
                "диапазон координат слишком узкий: в нём не разместить "
                "невырожденную пирамиду.")
        volume = whole("min_volume", 2)
        if volume < 1:
            raise ModelConfigError("min_volume должен быть положительным.")
        return {"min": low, "max": high, "min_volume": volume}

    def build(self, rng, **params) -> Instance:
        import sympy as sp

        cfg = self.normalize_params(params)

        for _ in range(400):
            a1, a2, a3, a4 = [
                sp.Matrix([rng.randint(cfg["min"], cfg["max"]) for _ in range(3)])
                for _ in range(4)
            ]
            mixed = (a2 - a1).dot((a3 - a1).cross(a4 - a1))
            # Смешанное произведение — шестикратный объём. Ноль означает
            # четыре точки в одной плоскости: пирамиды нет, а задание про
            # неё есть.
            if abs(mixed) < 6 * cfg["min_volume"]:
                continue

            plane234 = _plane(a2, a3, a4)
            plane134 = _plane(a1, a3, a4)
            normal = (a3 - a2).cross(a4 - a2)

            return PyramidInstance(
                values={
                    "a1": a1, "a2": a2, "a3": a3, "a4": a4,
                    "angle_a2a1a3": _angle(a2 - a1, a3 - a1),
                    "angle_a2a1a4": _angle(a2 - a1, a4 - a1),
                    "angle_a3a1a4": _angle(a3 - a1, a4 - a1),
                    "area_a1a3a4": _area(a1, a3, a4),
                    "area_a2a3a4": _area(a2, a3, a4),
                    "volume": sp.Rational(abs(mixed), 6),
                    "plane_a2a3a4": plane234,
                    "plane_a1a3a4": plane134,
                    "normal_a1": _primitive(normal),
                    "projection_a1": _projection(a1, a2, normal),
                    "height_a1": _distance(a1, a2, normal),
                    "height_a2": _distance(a2, a1, (a3 - a1).cross(a4 - a1)),
                },
                params=dict(cfg),
            )
        raise ModelError(
            "не удалось подобрать пирамиду в заданных границах — расширьте "
            "диапазон координат или уменьшите min_volume.")


def _length(vector):
    import sympy as sp

    return sp.sqrt(sum(component ** 2 for component in vector))


def _angle(first, second):
    """Плоский угол — точный, без плавающей точки в аргументе acos."""
    import sympy as sp

    return sp.acos(sp.radsimp(first.dot(second) / (_length(first) * _length(second))))


def _area(first, second, third):
    """Площадь треугольника — половина длины векторного произведения."""
    import sympy as sp

    return sp.Rational(1, 2) * _length((second - first).cross(third - first))


def _plane(first, second, third):
    """Уравнение плоскости через три точки, с целыми коэффициентами."""
    import sympy as sp

    from ..equation_text import normalise

    normal = (second - first).cross(third - first)
    point = sp.Matrix(sp.symbols("x y z")) - first
    return normalise(normal.dot(point), VARIABLES)


def _primitive(vector):
    """
    Направляющий вектор с целыми взаимно простыми координатами.

    Нормаль как есть бывает вида (12, -18, 30); студент запишет (2, -3, 5),
    и это тот же вектор. Ключ должен выглядеть так же.
    """
    import sympy as sp

    common = sp.gcd([abs(component) for component in vector])
    return sp.Matrix(vector) if common in (0, 1) else sp.Matrix(vector) / common


def _projection(point, plane_point, normal):
    """Проекция точки на плоскость, заданную точкой и нормалью."""
    import sympy as sp

    shift = (point - plane_point).dot(normal) / normal.dot(normal)
    return sp.Matrix(point - shift * normal)


def _distance(point, plane_point, normal):
    """Расстояние от точки до плоскости — точное."""
    import sympy as sp

    return sp.Abs((point - plane_point).dot(normal)) / _length(normal)


MODEL = PyramidModel()
