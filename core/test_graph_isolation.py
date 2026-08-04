"""
Изоляция исполнения графов (этап 4).

План, §9: `generator_service` исполнял произвольные графы в том же
процессе, где держит соединение с БД. Граф — пользовательский контент, с
пакетами узлов буквально сторонний Python. Один плохой граф получал и
процесс, и базу.

Здесь проверяется, что дыра закрыта именно там, где описана:
  * граф исполняется в ДРУГОМ процессе;
  * у этого процесса нет соединения с БД;
  * бесконечный цикл снимается по таймауту, а сервис живёт;
  * падение уносит рабочий процесс, а не вызывающего;
  * результат пересекает границу без потерь.

Запуск: python -m unittest core.test_graph_isolation  (из корня монорепо)
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core.answers import NumberSpec  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.graph import isolation  # noqa: E402
from core.graph.isolation import (  # noqa: E402
    IsolatedGraphRunner, WorkerError, WorkerTimeout, isolation_enabled,
)
from core.task import StaticTask  # noqa: E402
from exercises.graph.generators import EXAMPLE_SIMPLE_TASK  # noqa: E402


class RunnerTestBase(unittest.TestCase):

    def setUp(self):
        self.runner = IsolatedGraphRunner(timeout=15)
        self.addCleanup(self.runner.close)


# ======================================================================
#  Граница процесса
# ======================================================================

class ProcessBoundaryTests(RunnerTestBase):

    def test_graph_runs_in_another_process(self):
        # Самое прямое доказательство изоляции: pid не наш.
        self.runner.run(EXAMPLE_SIMPLE_TASK)
        worker = self.runner._worker  # noqa: SLF001
        self.assertTrue(worker.alive)
        self.assertNotEqual(worker._process.pid, os.getpid())  # noqa: SLF001

    def test_worker_does_not_load_the_service(self):
        """
        Рабочий процесс — не сервер: ни роутеров, ни стора сессий.

        Про `core.repository` тест сознательно НЕ спрашивает. Модуль там
        окажется: `core/__init__.py` в этом репозитории импортирует слой
        доступа сразу, и достаточно тронуть что угодно под `core`. Но
        загруженный модуль — не граница: узел, который хочет добраться до
        базы, откроет файл через `sqlite3` и без него. Граница проходит
        по живому соединению (следующий тест) и по правам процесса на
        файловую систему, а последнее — дело развёртывания, а не кода.
        """
        import json
        import subprocess

        script = (
            "import json, sys;"
            "from core.graph.worker import _handle;"
            "spec = json.loads(sys.argv[1]);"
            "_handle({'spec': spec});"
            "loaded = [m for m in sys.modules"
            " if m.startswith('generator_service')];"
            "print(json.dumps(loaded))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, json.dumps(EXAMPLE_SIMPLE_TASK)],
            cwd=_MONOREPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), [],
                         "в процесс исполнения графа затащили сервис")

    def test_worker_holds_no_sqlite_connection(self):
        """
        Та самая угроза §9, проверенная фактом: у процесса, исполняющего
        граф, нет живого соединения с базой. Раньше оно было — граф
        работал внутри процесса сервиса.
        """
        import json
        import subprocess

        script = (
            "import json, sqlite3, sys;"
            "from core.graph.worker import _handle;"
            "spec = json.loads(sys.argv[1]);"
            "_handle({'spec': spec});"
            "import gc;"
            "conns = [o for o in gc.get_objects()"
            " if isinstance(o, sqlite3.Connection)];"
            "print(len(conns))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, json.dumps(EXAMPLE_SIMPLE_TASK)],
            cwd=_MONOREPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0",
                         "у процесса исполнения графа оказалось соединение с БД")

    def test_ping_reaches_the_worker(self):
        response = self.runner._worker.request(  # noqa: SLF001
            {"op": "ping"}, timeout=10)
        self.assertTrue(response.get("pong"))


class ResultCrossesTheBoundaryTests(RunnerTestBase):

    def test_task_is_rebuilt_on_this_side(self):
        task = isolation.run_graph(EXAMPLE_SIMPLE_TASK, runner=self.runner)
        self.assertIsInstance(task, StaticTask)
        self.assertTrue(task.statement)

    def test_statement_blocks_survive(self):
        task = isolation.run_graph(EXAMPLE_SIMPLE_TASK, runner=self.runner)
        text = " ".join(b.render_plain() for b in task.statement)
        self.assertTrue(text.strip())

    def test_seed_makes_the_result_reproducible(self):
        first = isolation.run_graph(EXAMPLE_SIMPLE_TASK, seed=42,
                                    runner=self.runner)
        second = isolation.run_graph(EXAMPLE_SIMPLE_TASK, seed=42,
                                     runner=self.runner)
        self.assertEqual(
            [b.render_plain() for b in first.statement],
            [b.render_plain() for b in second.statement])

    def test_different_seeds_differ(self):
        seen = set()
        for seed in range(6):
            task = isolation.run_graph(EXAMPLE_SIMPLE_TASK, seed=seed,
                                       runner=self.runner)
            seen.add(" ".join(b.render_plain() for b in task.statement))
        self.assertGreater(len(seen), 1, "сид не влияет — изоляция ломает случайность")


class TaskRoundTripTests(unittest.TestCase):
    """Разбор задания обратно — то, чем результат пересекает границу."""

    def test_plain_task_round_trip(self):
        task = StaticTask(statement=[TextBlock("условие")],
                          answer=[TextBlock("ответ")], meta={"partition_id": 7})
        back = StaticTask.from_dict(task.to_dict())
        self.assertEqual([b.render_plain() for b in back.statement], ["условие"])
        self.assertEqual(back.meta["partition_id"], 7)

    def test_answer_spec_survives(self):
        task = StaticTask(statement=[TextBlock("у")], answer=[],
                          answer_spec=NumberSpec(value=9.8, unit="м/с^2"))
        back = StaticTask.from_dict(task.to_dict())
        self.assertTrue(back.is_checkable)
        self.assertTrue(back.answer_spec.check("9.8 м/с^2").accepted)

    def test_widgets_are_not_restored_from_the_dict(self):
        # Виджеты вычисляются из спецификации; восстанавливать их из
        # словаря значило бы завести второй источник правды.
        task = StaticTask(statement=[], answer=[],
                          answer_spec=NumberSpec(value=1.0))
        back = StaticTask.from_dict(task.to_dict())
        self.assertEqual(back.to_dict()["widgets"], task.to_dict()["widgets"])


# ======================================================================
#  Живучесть
# ======================================================================

class TimeoutTests(unittest.TestCase):
    """
    То, ради чего §9 назвал дыру работающей: бесконечный цикл в графе.

    До изоляции такой граф вешал процесс сервиса вместе с соединением к
    базе, и снять его было нечем — прервать чужой поток в Python нельзя.
    """

    def test_caller_does_not_block_and_worker_is_killed(self):
        """
        Главное свойство: вызывающий получает управление обратно, а
        процесс с графом снимается.

        Оговорка честности: граф здесь не бесконечный — просто таймаут
        меньше, чем время ответа. Проверяется механизм (не дождались →
        сняли → освободили вызывающего), а он один и тот же независимо от
        того, почему процесс молчит.
        """
        runner = IsolatedGraphRunner(timeout=0.001)
        self.addCleanup(runner.close)
        worker = runner._worker  # noqa: SLF001

        with self.assertRaises(WorkerTimeout):
            runner.run(EXAMPLE_SIMPLE_TASK)

        self.assertFalse(worker.alive, "молчащий процесс обязан быть снят")

    def test_pool_recovers_after_a_timeout(self):
        # Один зависший граф не должен выводить из строя весь сервис.
        runner = IsolatedGraphRunner(timeout=0.001)
        self.addCleanup(runner.close)
        with self.assertRaises(WorkerTimeout):
            runner.run(EXAMPLE_SIMPLE_TASK)
        runner.timeout = 15
        self.assertTrue(runner.run(EXAMPLE_SIMPLE_TASK).get("ok"))

    def test_timeout_is_a_subclass_of_worker_error(self):
        # Вызывающему достаточно ловить WorkerError, чтобы не пропустить
        # ни отказ процесса, ни таймаут.
        self.assertTrue(issubclass(WorkerTimeout, WorkerError))


class WorkerRecyclingTests(unittest.TestCase):

    def test_worker_is_recycled_after_max_requests(self):
        # Постоянный процесс копит утечки чужого кода; переработка по
        # счётчику — цена, которую платят раз в сотни запросов.
        runner = IsolatedGraphRunner(max_requests=3, timeout=15)
        self.addCleanup(runner.close)
        runner.run(EXAMPLE_SIMPLE_TASK)
        first_pid = runner._worker._process.pid  # noqa: SLF001
        for _ in range(3):
            runner.run(EXAMPLE_SIMPLE_TASK)
        self.assertNotEqual(runner._worker._process.pid, first_pid)  # noqa: SLF001

    def test_dead_worker_is_restarted(self):
        runner = IsolatedGraphRunner(timeout=15)
        self.addCleanup(runner.close)
        runner.run(EXAMPLE_SIMPLE_TASK)
        runner._worker.stop()  # noqa: SLF001
        self.assertTrue(runner.run(EXAMPLE_SIMPLE_TASK).get("ok"))


# ======================================================================
#  Ошибки графа против отказов процесса
# ======================================================================

class ErrorKindsTests(RunnerTestBase):
    """
    Ошибка В ГРАФЕ и отказ ПРОЦЕССА — разные вещи, и путать их нельзя:
    первая это сообщение автору, вторая — сбой инфраструктуры.
    """

    def test_broken_graph_is_a_response_not_a_crash(self):
        response = self.runner.run({"nodes": [{"id": "a", "type": "нет-такого"}],
                                    "edges": []})
        self.assertFalse(response["ok"])
        self.assertIn(response["kind"], ("validation", "internal"))

    def test_graph_without_final_node_is_reported(self):
        response = self.runner.run({"nodes": [], "edges": []})
        self.assertFalse(response["ok"])

    def test_worker_survives_a_broken_graph(self):
        self.runner.run({"nodes": [{"id": "a", "type": "нет-такого"}],
                         "edges": []})
        self.assertTrue(self.runner.run(EXAMPLE_SIMPLE_TASK).get("ok"))

    def test_run_graph_raises_on_broken_graph(self):
        with self.assertRaises(WorkerError):
            isolation.run_graph({"nodes": [], "edges": []}, runner=self.runner)

    def test_malformed_request_is_reported(self):
        response = self.runner._worker.request(  # noqa: SLF001
            {"spec": "не словарь"}, timeout=10)
        self.assertFalse(response["ok"])


# ======================================================================
#  Переключатель
# ======================================================================

class ToggleTests(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("GRAPH_ISOLATION", None)

    def test_enabled_by_default(self):
        os.environ.pop("GRAPH_ISOLATION", None)
        self.assertTrue(isolation_enabled())

    def test_can_be_disabled(self):
        for value in ("0", "false", "no", "off", "OFF"):
            with self.subTest(value=value):
                os.environ["GRAPH_ISOLATION"] = value
                self.assertFalse(isolation_enabled())

    def test_disabled_path_still_produces_a_task(self):
        os.environ["GRAPH_ISOLATION"] = "0"
        task = isolation.run_graph(EXAMPLE_SIMPLE_TASK)
        self.assertIsInstance(task, StaticTask)

    def test_both_paths_agree_on_the_same_seed(self):
        # Изоляция не должна менять результат — иначе включение её на
        # развёртывании тихо поменяло бы задания у студентов.
        os.environ["GRAPH_ISOLATION"] = "0"
        direct = isolation.run_graph(EXAMPLE_SIMPLE_TASK, seed=7)
        os.environ.pop("GRAPH_ISOLATION", None)
        runner = IsolatedGraphRunner(timeout=15)
        self.addCleanup(runner.close)
        isolated = isolation.run_graph(EXAMPLE_SIMPLE_TASK, seed=7,
                                       runner=runner)
        self.assertEqual(
            [b.render_plain() for b in direct.statement],
            [b.render_plain() for b in isolated.statement])


# ======================================================================
#  Предпросмотр
# ======================================================================

class PreviewTests(RunnerTestBase):
    """Путь, куда приходят НЕСОХРАНЁННЫЕ графы прямо из редактора."""

    def test_preview_returns_runs(self):
        result = isolation.preview_graph_runs(
            EXAMPLE_SIMPLE_TASK, seeds=[1, 2, 3], runner=self.runner)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["runs"]), 3)

    def test_preview_includes_blocks(self):
        result = isolation.preview_graph_runs(
            EXAMPLE_SIMPLE_TASK, seeds=[1], runner=self.runner)
        self.assertTrue(result["runs"][0]["statement"])

    def test_preview_of_broken_graph_reports_errors(self):
        result = isolation.preview_graph_runs(
            {"nodes": [{"id": "a", "type": "нет-такого"}], "edges": []},
            runner=self.runner)
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_graph_api_preview_uses_isolation(self):
        from core.graph_api import preview_graph
        result = preview_graph(EXAMPLE_SIMPLE_TASK, seeds=[1, 2])
        self.addCleanup(isolation.shutdown_shared)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["runs"]), 2)


class GeneratorGoesThroughIsolationTests(unittest.TestCase):

    def tearDown(self):
        isolation.shutdown_shared()

    def test_graph_partition_generates_a_task(self):
        from exercises.graph.generators import GraphConstructorGenerator
        generator = GraphConstructorGenerator(1, "граф", EXAMPLE_SIMPLE_TASK)
        task = generator.generate()
        self.assertIsInstance(task, StaticTask)

    def test_configure_replaces_the_graph(self):
        from exercises.graph.generators import GraphConstructorGenerator
        generator = GraphConstructorGenerator(1, "граф", {})
        generator.configure({"raw": EXAMPLE_SIMPLE_TASK})
        self.assertIsInstance(generator.generate(), StaticTask)


if __name__ == "__main__":
    unittest.main()
