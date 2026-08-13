"""
Стандарт моделей и первая модель по нему.

Главное, что здесь проверяется, — АРИФМЕТИКА, а не факт возврата
значения. Урок июльского разбора: в текстовом коме из двенадцати величин
неверная прожила ровно до тех пор, пока никто не пересчитал ответ руками
(docs/architecture/models_on_july.md, §2.1). Модель обещает спектр — тест
считает спектр независимо, через sympy, и сравнивает.

Запуск:
    python -m unittest core.test_models
"""

from __future__ import annotations

import keyword
import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sympy as sp  # noqa: E402

from core.models import DEFAULT_MODELS  # noqa: E402
from core.models.base import (  # noqa: E402
    OUTPUT_TYPES, Instance, Model, ModelConfigError, ModelError, Output,
    values_equivalent,
)
from core.models.linal_eigen import MODEL as EIGEN  # noqa: E402
from core.models.registry import ModelRegistry  # noqa: E402

SEEDS = range(40)


def _spectrum(matrix) -> list:
    """Спектр НЕЗАВИСИМО от модели: как его посчитал бы проверяющий."""
    out = []
    for value, multiplicity in matrix.eigenvals().items():
        out.extend([value] * multiplicity)
    return sorted(out)


class SpectrumTests(unittest.TestCase):
    """Модель обещает спектр — считаем его сами и сверяем."""

    def test_declared_spectrum_is_the_real_one(self):
        for seed in SEEDS:
            instance = EIGEN.build(random.Random(seed), size=3)
            with self.subTest(seed=seed):
                self.assertEqual(_spectrum(instance.values["matrix"]),
                                 instance.values["eigenvalues"])

    def test_matrix_is_integer(self):
        """
        Целочисленность — не косметика: дробная матрица превращает
        задание «найдите собственные значения» в вычислительное упражнение
        на обыкновенные дроби.
        """
        for seed in SEEDS:
            instance = EIGEN.build(random.Random(seed), size=3)
            with self.subTest(seed=seed):
                self.assertTrue(
                    all(x.is_Integer for x in instance.values["matrix"]))

    def test_eigenvectors_really_are_eigenvectors(self):
        for seed in SEEDS:
            instance = EIGEN.build(random.Random(seed), size=3)
            A = instance.values["matrix"]
            pairs = zip(instance.values["eigenvalues"],
                        instance.values["eigenvectors"])
            for lam, vector in pairs:
                with self.subTest(seed=seed, lam=lam):
                    self.assertEqual(A * vector, lam * vector)
                    self.assertNotEqual(vector, sp.zeros(*vector.shape))

    def test_char_poly_vanishes_exactly_on_the_spectrum(self):
        for seed in SEEDS:
            instance = EIGEN.build(random.Random(seed), size=3)
            poly = instance.values["char_poly"]
            # Переменная берётся из самого многочлена, а не пишется здесь
            # буквами: с зашитым написанием `subs` молча ничего не
            # подставляет, и тест проверяет равенство нулю выражения,
            # которое нулём быть и не обязано.
            variables = poly.free_symbols
            with self.subTest(seed=seed):
                self.assertEqual(len(variables), 1, variables)
                lam = next(iter(variables))
                for value in instance.values["eigenvalues"]:
                    self.assertEqual(poly.subs(lam, value), 0)

    def test_char_poly_variable_is_not_a_python_keyword(self):
        """
        `lambda` — ключевое слово Python: `parse_expr` спотыкается о него
        и падает на выражении целиком. Пока переменная звалась так,
        задание «выпишите характеристический многочлен» не принимало НИ
        ОДНОГО ответа, включая собственный эталон. Написание `lamda` —
        договорённость sympy ровно для этого случая; печатается оно всё
        равно как λ, так что студент разницы не видит.
        """
        for seed in SEEDS:
            poly = EIGEN.build(random.Random(seed), size=3).values["char_poly"]
            for symbol in poly.free_symbols:
                with self.subTest(seed=seed, symbol=symbol.name):
                    self.assertFalse(keyword.iskeyword(symbol.name))

    def test_trace_and_determinant_agree_with_the_spectrum(self):
        """Сумма и произведение λ — независимая перекрёстная проверка."""
        for seed in SEEDS:
            instance = EIGEN.build(random.Random(seed), size=3)
            values = instance.values["eigenvalues"]
            with self.subTest(seed=seed):
                self.assertEqual(instance.values["trace"], sum(values))
                product = 1
                for v in values:
                    product *= v
                self.assertEqual(instance.values["determinant"], product)

    def test_matrix_is_not_triangular(self):
        """
        У треугольной матрицы спектр стоит на диагонали — задание
        превращается в «перепишите три числа».
        """
        for seed in SEEDS:
            A = EIGEN.build(random.Random(seed), size=3).values["matrix"]
            with self.subTest(seed=seed):
                self.assertFalse(A.is_upper or A.is_lower)

    def test_sizes_two_to_four_all_work(self):
        for size in (2, 3, 4):
            instance = EIGEN.build(random.Random(5), size=size)
            with self.subTest(size=size):
                self.assertEqual(instance.values["matrix"].shape, (size, size))
                self.assertEqual(len(instance.values["eigenvalues"]), size)
                self.assertEqual(_spectrum(instance.values["matrix"]),
                                 instance.values["eigenvalues"])


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_gives_the_same_instance(self):
        """
        Воспроизводимость — это то, ради чего build принимает rng, а не
        дёргает глобальный random: два студента с одним вариантом обязаны
        получить одну матрицу.
        """
        first = EIGEN.build(random.Random(3), size=3)
        second = EIGEN.build(random.Random(3), size=3)
        self.assertEqual(first.values["matrix"], second.values["matrix"])
        self.assertEqual(first.values["eigenvalues"],
                         second.values["eigenvalues"])

    def test_different_seeds_give_different_instances(self):
        seen = {str(EIGEN.build(random.Random(s), size=3).values["matrix"])
                for s in SEEDS}
        self.assertGreater(len(seen), len(SEEDS) // 2)


class ParamTests(unittest.TestCase):
    def test_distinct_by_default(self):
        for seed in SEEDS:
            values = EIGEN.build(random.Random(seed), size=3).values["eigenvalues"]
            with self.subTest(seed=seed):
                self.assertEqual(len(set(values)), len(values))

    def test_repeated_allows_multiplicity(self):
        repeats = 0
        for seed in SEEDS:
            values = EIGEN.build(random.Random(seed), size=3,
                                 repeated=True).values["eigenvalues"]
            if len(set(values)) < len(values):
                repeats += 1
        self.assertGreater(repeats, 0, "кратные λ не появляются вовсе")

    def test_range_is_respected(self):
        for seed in SEEDS:
            values = EIGEN.build(random.Random(seed), size=3,
                                 min=1, max=9).values["eigenvalues"]
            with self.subTest(seed=seed):
                self.assertTrue(all(1 <= v <= 9 for v in values))

    def test_impossible_range_is_a_config_error(self):
        """
        Не невезение, а противоречие: трёх различных λ в [0, 1] не бывает
        ни при каком зерне. Перебрасывать бессмысленно — и тип ошибки
        обязан это различать.
        """
        with self.assertRaises(ModelConfigError):
            EIGEN.build(random.Random(0), size=3, min=0, max=1)

    def test_repeated_makes_the_same_range_possible(self):
        instance = EIGEN.build(random.Random(0), size=3, min=0, max=1,
                               repeated=True)
        self.assertEqual(len(instance.values["eigenvalues"]), 3)

    def test_absurd_size_is_refused(self):
        for size in (1, 7):
            with self.subTest(size=size), self.assertRaises(ModelConfigError):
                EIGEN.build(random.Random(0), size=size)

    def test_config_error_is_a_model_error(self):
        # Вызывающие, которым различие не нужно, ловят один тип.
        self.assertTrue(issubclass(ModelConfigError, ModelError))


class VocabularyTests(unittest.TestCase):
    """
    Словарь типов величин продублирован в `core.models` намеренно — чтобы
    модели не тянули за собой `core.graph` (первая же такая ссылка дала
    цикл импорта, и реестр моделей строился пустым). Дубликат без сторожа
    расходится молча, поэтому сторож здесь.
    """

    def test_every_model_type_is_a_real_port_type(self):
        from core.graph.port_types import PortType

        self.assertTrue(OUTPUT_TYPES <= {t.value for t in PortType},
                        "в словаре моделей есть тип, которого нет у портов")

    def test_exclusions_are_deliberate_and_named(self):
        from core.graph.port_types import PortType

        self.assertEqual({t.value for t in PortType} - set(OUTPUT_TYPES),
                         {"task", "any"},
                         "у портов появился тип, о котором словарь моделей "
                         "не знает: включить его или объяснить, почему нет")

    def test_a_model_cannot_declare_a_whole_task(self):
        # Граница §4.3: модель не решает, какое из неё задание.
        self.assertNotIn("task", OUTPUT_TYPES)


class EquivalenceTests(unittest.TestCase):
    def test_eigenvector_up_to_a_factor(self):
        """
        Тот самый случай, ради которого `equivalent` существует: ответ
        `2v` верен так же, как `v`, а сравнение по значению его забракует.
        """
        instance = EIGEN.build(random.Random(4), size=3)
        scaled = [2 * v for v in instance.values["eigenvectors"]]
        self.assertTrue(instance.equivalent("eigenvectors", scaled))
        self.assertFalse(
            values_equivalent(instance.values["eigenvectors"], scaled),
            "сравнение по значению приняло масштабированный вектор — "
            "тогда предметная эквивалентность была бы не нужна")

    def test_negative_factor_is_also_the_same_eigenvector(self):
        instance = EIGEN.build(random.Random(4), size=3)
        flipped = [-v for v in instance.values["eigenvectors"]]
        self.assertTrue(instance.equivalent("eigenvectors", flipped))

    def test_zero_vector_is_not_an_eigenvector(self):
        instance = EIGEN.build(random.Random(4), size=3)
        n = instance.values["matrix"].rows
        zeros = [sp.zeros(n, 1) for _ in instance.values["eigenvectors"]]
        self.assertFalse(instance.equivalent("eigenvectors", zeros))

    def test_spectrum_order_does_not_matter(self):
        instance = EIGEN.build(random.Random(4), size=3)
        values = instance.values["eigenvalues"]
        self.assertTrue(instance.equivalent("eigenvalues", list(reversed(values))))

    def test_multiplicity_does_matter(self):
        # «1, 1, 2» и «1, 2» — разные ответы, хотя множества совпадают.
        self.assertFalse(values_equivalent([1, 1, 2], [1, 2]))

    def test_halves_and_decimals_are_the_same_number(self):
        self.assertTrue(values_equivalent(sp.Rational(1, 2), 0.5))

    def test_wrong_value_is_rejected(self):
        instance = EIGEN.build(random.Random(4), size=3)
        wrong = [v + 1 for v in instance.values["eigenvalues"]]
        self.assertFalse(instance.equivalent("eigenvalues", wrong))


class InstanceTests(unittest.TestCase):
    def test_get_reaches_both_baskets(self):
        instance = Instance(values={"a": 1}, blocks={"b": "блок"})
        self.assertEqual(instance.get("a"), 1)
        self.assertEqual(instance.get("b"), "блок")
        with self.assertRaises(KeyError):
            instance.get("нет")


class _Broken(Model):
    name = "broken"
    title = "Сломанная"
    category = "compute"
    OUTPUTS = [Output("value", "number"), Output("picture", "image")]

    def build(self, rng, **params):
        return Instance(values={"value": 1, "picture": "не блок"})


class CheckInstanceTests(unittest.TestCase):
    """
    Забытая величина обязана падать сразу и внятно.

    Иначе в провод уходит None и всплывает через три узла чем-нибудь
    вроде «NoneType не поддерживает вычитание» — сообщение, по которому
    автор графа причину не найдёт.
    """

    def test_missing_value_is_named(self):
        model = _Broken()
        instance = Instance(values={"value": 1})
        with self.assertRaises(ModelError) as ctx:
            model.check_instance(instance)
        self.assertIn("picture", str(ctx.exception))

    def test_block_typed_value_must_live_in_blocks(self):
        model = _Broken()
        with self.assertRaises(ModelError) as ctx:
            model.check_instance(model.build(random.Random(0)))
        self.assertIn("blocks", str(ctx.exception))


class RegistryTests(unittest.TestCase):
    def test_default_registry_holds_the_first_model(self):
        self.assertIn("linal_eigen", DEFAULT_MODELS.names())
        self.assertIs(DEFAULT_MODELS.get("linal_eigen"), EIGEN)

    def test_unknown_model_lists_what_is_available(self):
        with self.assertRaises(KeyError) as ctx:
            DEFAULT_MODELS.get("нет такой")
        self.assertIn("linal_eigen", str(ctx.exception))

    def test_duplicate_name_is_refused(self):
        registry = ModelRegistry()
        registry.register(_Broken())
        with self.assertRaises(ValueError):
            registry.register(_Broken())

    def test_unknown_port_type_is_caught_at_registration(self):
        """
        Опечатка в типе величины иначе всплыла бы у автора графа при
        генерации задания — далеко от причины и в чужих терминах.
        """
        class Typo(Model):
            name = "typo"
            OUTPUTS = [Output("x", "matrics")]

        with self.assertRaises(ValueError) as ctx:
            ModelRegistry().register(Typo())
        self.assertIn("matrics", str(ctx.exception))

    def test_model_without_outputs_is_refused(self):
        class Empty(Model):
            name = "empty"

        with self.assertRaises(ValueError):
            ModelRegistry().register(Empty())

    def test_duplicate_output_name_is_refused(self):
        class Twice(Model):
            name = "twice"
            OUTPUTS = [Output("x", "number"), Output("x", "expr")]

        with self.assertRaises(ValueError):
            ModelRegistry().register(Twice())


if __name__ == "__main__":
    unittest.main()
