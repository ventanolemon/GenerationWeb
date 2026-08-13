"""
Узел, собранный из модели.

Проверяется главное обещание стандарта: МОДЕЛЬ НЕ ЗНАЕТ, КАКОЕ ЗАДАНИЕ ИЗ
НЕЁ СОБЕРУТ. Два графа ниже отличаются только разводкой проводов — одна и
та же модель даёт то «найдите второе собственное значение», то «найдите
след». Пока это не проверено на живом графе, стандарт остаётся
декларацией.

Второе, что здесь сторожится, — разница между невезением и ошибкой
автора. Противоречивые параметры не чинятся перебросом зерна, и если бы
они ехали как RetryGeneration, автор графа увидел бы «исчерпаны попытки»
вместо «в диапазоне [0, 1] трёх различных λ не бывает».

Запуск:
    python -m unittest core.test_model_nodes
"""

from __future__ import annotations

import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.graph.errors import GraphValidationError, RetryGeneration  # noqa: E402
from core.graph.executor import GraphExecutor  # noqa: E402
from core.graph.node import ExecContext  # noqa: E402
from core.graph.nodes import DEFAULT_REGISTRY  # noqa: E402
from core.graph.nodes.model_nodes import model_node_class  # noqa: E402
from core.graph.port_types import PortType  # noqa: E402
from core.graph.spec import GraphSpec  # noqa: E402
from core.models.base import Instance, Model, ModelConfigError, ModelError, Output  # noqa: E402
from core.models.linal_eigen import MODEL as EIGEN  # noqa: E402

TYPE_ID = "model_linal_eigen"


class PortsFromDeclarationTests(unittest.TestCase):
    """Порты не пишутся руками — они и есть объявление модели."""

    def test_node_is_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has(TYPE_ID))

    def test_outputs_match_the_models_declaration(self):
        cls = DEFAULT_REGISTRY.get(TYPE_ID)
        self.assertEqual([(p.name, p.type.value) for p in cls.OUTPUTS],
                         [(o.name, o.type) for o in EIGEN.OUTPUTS])

    def test_types_are_real_port_types(self):
        cls = DEFAULT_REGISTRY.get(TYPE_ID)
        by_name = {p.name: p.type for p in cls.OUTPUTS}
        self.assertIs(by_name["matrix"], PortType.MATRIX)
        self.assertIs(by_name["eigenvalues"], PortType.LIST)
        self.assertIs(by_name["char_poly"], PortType.EXPR)
        self.assertIs(by_name["trace"], PortType.NUMBER)

    def test_it_is_a_source(self):
        # Модель строит ситуацию из зерна: входов у неё быть не может.
        self.assertEqual(DEFAULT_REGISTRY.get(TYPE_ID).INPUTS, [])

    def test_form_comes_from_the_models_params(self):
        cls = DEFAULT_REGISTRY.get(TYPE_ID)
        self.assertEqual(cls.PARAMS_SCHEMA, EIGEN.PARAMS)

    def test_palette_shows_the_model_by_its_own_name(self):
        """
        Автор ищет «Матрица с известным спектром», а не узел «Модель», в
        котором ещё надо угадать пункт выпадающего списка.
        """
        entry = next(e for e in DEFAULT_REGISTRY.palette()
                     if e["type_id"] == TYPE_ID)
        self.assertEqual(entry["display_name"], "Матрица с известным спектром")
        self.assertEqual(entry["category"], "linalg")
        self.assertTrue(entry["description"])


class ComputeTests(unittest.TestCase):
    def _run(self, **params):
        node = DEFAULT_REGISTRY.create(TYPE_ID, "m", params)
        return node.compute({}, ExecContext(rng=random.Random(5)))

    def test_every_declared_value_reaches_the_wire(self):
        out = self._run(size=3)
        self.assertEqual(sorted(out), sorted(EIGEN.output_names()))

    def test_params_reach_the_model(self):
        self.assertEqual(self._run(size=2)["matrix"].shape, (2, 2))

    def test_defaults_apply_when_the_form_is_empty(self):
        self.assertEqual(self._run()["matrix"].shape, (3, 3))

    def test_bool_param_survives_the_string_form(self):
        """
        Из импортированного графа галочка приходит строкой, и `"false"` в
        питоне истинно. Без приведения `repeated="false"` включало бы
        кратные собственные значения — ровно наоборот сказанному в форме.
        """
        node = DEFAULT_REGISTRY.create(TYPE_ID, "m", {"repeated": "false"})
        self.assertIs(node._call_params()["repeated"], False)
        node = DEFAULT_REGISTRY.create(TYPE_ID, "m", {"repeated": "true"})
        self.assertIs(node._call_params()["repeated"], True)

    def test_summary_shows_what_is_set(self):
        node = DEFAULT_REGISTRY.create(TYPE_ID, "m", {"size": 4})
        self.assertIn("size=4", node.summary())


class ErrorKindTests(unittest.TestCase):
    """Невезение и ошибка автора — разные вещи и разные исключения."""

    def test_contradictory_params_are_refused_at_build_time(self):
        with self.assertRaises(GraphValidationError) as ctx:
            DEFAULT_REGISTRY.create(TYPE_ID, "m",
                                    {"size": 3, "min": 0, "max": 1})
        self.assertIn("различных", str(ctx.exception))

    def test_garbage_in_a_number_field_is_refused(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create(TYPE_ID, "m", {"size": "три"})

    def test_bad_luck_asks_for_another_seed(self):
        """
        Модель, которой не повезло, обязана просить перегенерацию, а не
        ронять граф: так ведут себя все стохастические источники языка.
        """
        class Unlucky(Model):
            name = "unlucky"
            title = "Невезучая"
            category = "compute"
            OUTPUTS = [Output("x", "number")]

            def build(self, rng, **params):
                raise ModelError("не сложилось")

        node = model_node_class(Unlucky())("m", {})
        with self.assertRaises(RetryGeneration):
            node.compute({}, ExecContext(rng=random.Random(0)))

    def test_forgotten_value_is_reported_by_name(self):
        class Forgetful(Model):
            name = "forgetful"
            title = "Забывчивая"
            category = "compute"
            OUTPUTS = [Output("x", "number"), Output("y", "number")]

            def build(self, rng, **params):
                return Instance(values={"x": 1})

        node = model_node_class(Forgetful())("m", {})
        with self.assertRaises(RetryGeneration) as ctx:
            node.compute({}, ExecContext(rng=random.Random(0)))
        self.assertIn("y", str(ctx.exception))


class OneModelTwoTasksTests(unittest.TestCase):
    """
    Центральное обещание стандарта на живом графе.

    Оба графа держат один и тот же узел модели с одними параметрами.
    Различаются они ровно одним проводом — и это уже разные задания.
    """

    @staticmethod
    def _graph(answer_port: str, statement: str):
        return {"nodes": [
            {"id": "m", "type": TYPE_ID, "params": {"size": 3}},
            {"id": "b", "type": "matrix_block",
             "params": {"env": "pmatrix", "prefix": "A"}},
            {"id": "λ", "type": "list_get",
             "params": {"elem_type": "number", "index": 1}},
            {"id": "t", "type": "task",
             "params": {"statement": statement, "slots": ["ответ:number"]}},
        ], "edges": [
            {"from": "m:matrix", "to": "b:in"},
            {"from": "b:out", "to": "t:blocks"},
            {"from": "m:eigenvalues", "to": "λ:list"},
            {"from": f"{answer_port}", "to": "t:ответ"},
        ]}

    def test_second_eigenvalue_task(self):
        graph = self._graph("λ:out", "Найдите второе собственное значение.")
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertTrue(task.is_checkable)
        answer = float(task.answer_spec.accepted_examples()[0])
        # Ответ сверяем НЕЗАВИСИМО — по самой матрице из условия.
        matrix = self._matrix(task)
        spectrum = sorted(sum(([k] * v for k, v in matrix.eigenvals().items()),
                              []))
        self.assertEqual(answer, float(spectrum[1]))

    def test_trace_task_from_the_same_model(self):
        graph = self._graph("m:trace", "Найдите след матрицы.")
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        answer = float(task.answer_spec.accepted_examples()[0])
        self.assertEqual(answer, float(self._matrix(task).trace()))

    def test_the_two_tasks_ask_different_things(self):
        """
        Если бы обе разводки давали один ответ, тест выше ничего бы не
        доказывал — совпадение проверяем явно.
        """
        differ = 0
        for _ in range(20):
            first = GraphExecutor(GraphSpec.parse(
                self._graph("λ:out", "λ₂?"))).run()
            second = GraphExecutor(GraphSpec.parse(
                self._graph("m:trace", "след?"))).run()
            a = float(first.answer_spec.accepted_examples()[0])
            b = float(second.answer_spec.accepted_examples()[0])
            if a != b:
                differ += 1
        self.assertGreater(differ, 10)

    def test_the_task_is_checkable(self):
        from core.interactive import session_from_task

        graph = self._graph("m:trace", "Найдите след матрицы.")
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        session = session_from_task(task)
        self.assertTrue(
            session.submit(task.answer_spec.accepted_examples()[0]).correct)

    @staticmethod
    def _matrix(task):
        """Матрица из блока условия — то, что реально увидел студент."""
        import re

        import sympy as sp

        latex = "".join(b.render_plain() for b in task.statement)
        body = re.search(r"pmatrix\}(.+?)\\end\{pmatrix", latex, re.S)
        rows = [[sp.sympify(x.strip()) for x in row.split("&")]
                for row in body.group(1).split(r"\\") if row.strip()]
        return sp.Matrix(rows)


class ImportOrderTests(unittest.TestCase):
    """
    Реестр узлов не должен зависеть от того, что импортировали первым.

    Настоящий дефект, пойманный здесь. `core.models.registry` сверял тип
    величины с PortType — и этим замыкал круг: `core.graph` тянет узлы,
    узлы тянут модели, модели тянут `core.graph`. Если первым импортировать
    `core.models`, узлы получали ПОЛУСОБРАННЫЙ модуль моделей с пустым
    реестром и молча строили палитру без единой модели.

    Спрятался дефект ровно потому, что каждый тестовый модуль по
    отдельности проходил: порядок импорта в них разный. Поэтому проверка
    и делается в отдельном процессе — иначе она проверяла бы уже
    загруженные модули, а не загрузку.
    """

    def test_models_do_not_import_the_graph(self):
        import subprocess

        code = ("import sys; import core.models; "
                "print(any(m == 'core.graph' or m.startswith('core.graph.') "
                "for m in sys.modules))")
        out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False",
                         "core.models потянул за собой core.graph — "
                         f"цикл вернулся. {out.stderr}")

    def test_registry_is_complete_when_models_are_imported_first(self):
        import subprocess

        code = ("import core.models; "
                "from core.graph.nodes import DEFAULT_REGISTRY; "
                f"print(DEFAULT_REGISTRY.has({TYPE_ID!r}))")
        out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "True",
                         f"модель пропала из палитры. {out.stderr}")


class WrongTypeIsCaughtWhenWiringTests(unittest.TestCase):
    def test_matrix_cannot_be_wired_into_a_number_slot(self):
        """
        Типы величин объявлены не для красоты: несовместимый провод
        обязан ловиться при сборке графа, а не при выдаче задания.
        """
        graph = {"nodes": [
            {"id": "m", "type": TYPE_ID, "params": {}},
            {"id": "d", "type": "matrix_det", "params": {}},
        ], "edges": [{"from": "m:trace", "to": "d:in"}]}
        with self.assertRaises(GraphValidationError):
            GraphExecutor(GraphSpec.parse(graph))


if __name__ == "__main__":
    unittest.main()
