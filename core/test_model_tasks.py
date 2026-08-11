"""
Задания на моделях: то, чем модели доходят до студента.

До этого каталога пять моделей были написаны, оттестированы и видны в
палитре — и ни одна не выдавалась: разделы обслуживались старыми
код-генераторами. Модель без графа остаётся инструментом, которым никто
не пользуется, поэтому здесь проверяется не «граф валиден», а «задание
можно выдать»: оно собирается, оно ПРОВЕРЯЕМО, и его собственный ответ
проходит собственную проверку.

Последнее — не формальность. Ровно на нём поймана ошибка: у задания
«выпишите характеристический многочлен» не находилось ни одного
принимаемого примера, потому что переменной была `lambda` — ключевое
слово Python, на котором разбор ответа падает целиком.

Запуск:
    python -m unittest core.test_model_tasks
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import bootstrap  # noqa: E402
from core import Repository  # noqa: E402
from core.graph.executor import GraphExecutor  # noqa: E402
from core.graph.spec import GraphSpec  # noqa: E402
from core.interactive import session_from_task  # noqa: E402
from exercises.model_tasks import TASKS  # noqa: E402

WORDS = Path(_ROOT) / "resources" / "words"
SHIPPED_DB = Path(_ROOT) / "resources" / "users_database.db"


def _run(name: str):
    return GraphExecutor(GraphSpec.parse(TASKS[name]["graph"])).run()


class EveryTaskIsIssuableTests(unittest.TestCase):
    """Главное: задание собирается, проверяемо и принимает свой же ответ."""

    def test_graph_executes(self):
        for name in TASKS:
            with self.subTest(name=name):
                self.assertTrue(_run(name).statement)

    def test_task_is_checkable(self):
        for name in TASKS:
            with self.subTest(name=name):
                self.assertTrue(_run(name).is_checkable,
                                "задание без проверки — то, от чего уходили")

    def test_reference_answer_passes_its_own_check(self):
        """
        Инвариант «предпросмотр не врёт» отбрасывает пример, не прошедший
        `check`. Пустой список примеров означает, что эталон не проходит
        собственную проверку, — так и нашлась переменная `lambda`.
        """
        for name in TASKS:
            task = _run(name)
            examples = task.answer_spec.accepted_examples()
            with self.subTest(name=name):
                self.assertTrue(examples, "нет ни одного принимаемого примера")
                self.assertTrue(
                    session_from_task(task).submit(examples[0]).correct)

    def test_statement_is_not_empty_and_shows_something(self):
        # Условие без блоков — задание, по которому нечего решать.
        for name in TASKS:
            task = _run(name)
            shown = "".join(b.render_plain() for b in task.statement)
            with self.subTest(name=name):
                self.assertGreater(len(shown.strip()), 20, shown)

    def test_different_seeds_give_different_tasks(self):
        """
        Раздел выдаёт варианты, а не одно задание на всех.

        Сравнивается ОТВЕТ, а не текст условия: у заданий по схемам
        условие — картинка, и её `render_plain` даёт одну и ту же
        подпись при разных чертежах. Сравнение по условию проходило бы
        на восьми заданиях и падало на двух, ничего при этом не проверив.
        """
        for name in TASKS:
            graph = dict(TASKS[name]["graph"])
            seen = set()
            for seed in range(4):
                spec = dict(graph, meta=dict(graph.get("meta", {}), seed=seed))
                task = GraphExecutor(GraphSpec.parse(spec)).run()
                seen.add(str(task.answer_spec.to_dict()))
            with self.subTest(name=name):
                self.assertGreater(len(seen), 1)


class CatalogueTests(unittest.TestCase):
    def test_partition_ids_are_unique(self):
        ids = [e["partition_id"] for e in TASKS.values()]
        self.assertEqual(len(set(ids)), len(ids))

    def test_partition_ids_are_in_the_reserved_range(self):
        """
        Диапазон 200+ свободен: у код-только разделов номера до сотни, у
        английского — 1000+. Пересечение увело бы задание в чужой раздел.
        """
        occupied = {gen.partition_id for _s, gen in bootstrap.CODE_GENERATORS
                    if gen.partition_id is not None}
        for entry in TASKS.values():
            with self.subTest(pid=entry["partition_id"]):
                self.assertTrue(200 <= entry["partition_id"] < 1000)
                self.assertNotIn(entry["partition_id"], occupied)

    def test_reserved_range_is_free_in_the_shipped_database(self):
        """
        Проверка не по коду, а по ФАЙЛУ БД, который уезжает пользователю.

        `ensure_graph_partition` заводит раздел с указанным номером — и
        если номер уже занят разделом из поставки, он не заведёт новый,
        а перепишет чужой: сменит имя, тип и содержимое у раздела,
        который кому-то уже выдан. Номера в коде и номера в файле — два
        разных источника, и сходятся они только пока за этим следят.
        """
        conn = sqlite3.connect(SHIPPED_DB)
        try:
            taken = {row[0] for row in conn.execute(
                "SELECT id FROM Partitions WHERE id BETWEEN 200 AND 999")}
        finally:
            conn.close()
        clash = taken & {e["partition_id"] for e in TASKS.values()}
        self.assertFalse(clash, f"номера заняты в поставке: {sorted(clash)}")

    def test_every_task_uses_a_model_node(self):
        # Каталог именно про модели: граф без модельного узла сюда попал
        # бы по ошибке и жил бы не там.
        for name, entry in TASKS.items():
            types = {n["type"] for n in entry["graph"]["nodes"]}
            with self.subTest(name=name):
                self.assertTrue(any(t.startswith("model_") for t in types),
                                sorted(types))

    def test_all_five_models_are_used(self):
        """
        Иначе часть работы так и осталась бы невыданной — ровно то, из-за
        чего каталог и появился.
        """
        used = {n["type"] for e in TASKS.values() for n in e["graph"]["nodes"]
                if n["type"].startswith("model_")}
        self.assertEqual(used, {
            "model_linal_eigen", "model_linal_triangle", "model_linal_pyramid",
            "model_opvs_circuit", "model_opvs_ccode",
        })


class BootstrapTests(unittest.TestCase):
    """Разделы заводятся при старте и переживают повторный запуск."""

    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        # Копия ПОСТАВЛЯЕМОЙ базы, а не пустой файл. Во-первых, схема по
        # разные стороны синка заводится по-разному (сервер создаёт
        # таблицы сам, десктоп полагается на этот файл), и на пустом
        # файле десктопная половина теста просто падает. Во-вторых, так
        # проверяется то, что происходит на самом деле: обновление
        # доезжает до базы, в которой уже лежат разделы и чужие правки.
        shutil.copyfile(SHIPPED_DB, self.db)
        self.repo = Repository(self.db)
        bootstrap.sync_database(self.repo, WORDS)

    def tearDown(self):
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _partitions(self) -> dict[int, object]:
        out = {}
        for subject in self.repo.list_subjects():
            for part in self.repo.list_partitions_for_subject(subject.id):
                out[part.id] = part
        return out

    def test_every_task_becomes_a_partition(self):
        found = self._partitions()
        for name, entry in TASKS.items():
            with self.subTest(name=name):
                part = found.get(entry["partition_id"])
                self.assertIsNotNone(part, "раздел не заведён")
                self.assertEqual(part.constracted, 4)
                self.assertEqual(part.subject_id, entry["subject_id"])

    def test_partitions_belong_to_the_product(self):
        """
        `owner_user_id IS NULL` — единственное, что по §8 пересекает
        границу организаций. Поставочный раздел с владельцем был бы виден
        одной организации и невидим остальным.
        """
        conn = sqlite3.connect(self.db)
        try:
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(Subjects)")}
            if "owner_user_id" not in columns:
                # Десктоп: одна копия базы на одного пользователя, границы
                # организаций там не существует и владельца в схеме нет.
                self.skipTest("владельцев нет в схеме десктопа")
            for entry in TASKS.values():
                owner = conn.execute(
                    "SELECT owner_user_id FROM Partitions p "
                    "JOIN Subjects s ON s.id = p.subject_id WHERE p.id = ?",
                    (entry["partition_id"],)).fetchone()
                with self.subTest(pid=entry["partition_id"]):
                    self.assertIsNone(owner[0])
        finally:
            conn.close()

    def test_second_run_changes_nothing(self):
        before = {pid: (p.name, p.constracted, p.subject_id)
                  for pid, p in self._partitions().items()}
        bootstrap.sync_database(self.repo, WORDS)
        after = {pid: (p.name, p.constracted, p.subject_id)
                 for pid, p in self._partitions().items()}
        self.assertEqual(before, after)

    def test_registry_serves_every_task(self):
        registry = bootstrap.build_registry(self.repo, WORDS)
        for name, entry in TASKS.items():
            with self.subTest(name=name):
                self.assertTrue(registry.has(entry["partition_id"]))
                task = registry.get(entry["partition_id"]).generate()
                self.assertTrue(task.is_checkable)

    def test_old_generators_are_still_there(self):
        """
        Новые разделы заведены РЯДОМ, а не вместо: замена сменила бы
        содержимое уже выданных домашних заданий и разошлась бы с
        накопленной статистикой попыток.
        """
        found = self._partitions()
        for _subject, gen in bootstrap.CODE_GENERATORS:
            if gen.partition_id is not None:
                with self.subTest(pid=gen.partition_id):
                    self.assertIn(gen.partition_id, found)


if __name__ == "__main__":
    unittest.main()
