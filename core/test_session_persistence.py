"""
Интерактивные сессии вне памяти процесса (этап 4 из public_api.md).

До этого живые InteractiveTask лежали в dict процесса, и это ограничивало
развёртывание: за балансировщиком второй ход той же сессии приходил в
другой процесс и не находил её, а перезапуск сервиса ронял все активные
тренажёры. Проверяем, что теперь:

  * снимок состояния снимается и возвращается без потери прогресса;
  * ДРУГОЙ экземпляр стора (модель второго процесса) поднимает сессию из БД
    и продолжает её с того же места;
  * снимок обновляется после каждого хода, а не отстаёт на один;
  * протухшее, удалённое и неподнимаемое чистится, а не воскресает;
  * тип задания, не умеющий сниматься, продолжает жить в памяти — тихая
    деградация, а не отказ.

Запуск: python -m unittest core.test_session_persistence -v  (из корня монорепо)
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core import InteractiveTask, TurnResult  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.repository import Repository  # noqa: E402
from exercises.english.generators import WordsSession  # noqa: E402
from generator_service.session_store import SessionStore  # noqa: E402

WORDS = {"cat": "кот", "dog": "собака", "fox": "лиса", "owl": "сова"}


class _OpaqueTask(InteractiveTask):
    """Задание, не умеющее сниматься: state() отдаёт None (умолчание базы)."""

    def initial_prompt(self):
        return [TextBlock("?")]

    def submit(self, user_input: str) -> TurnResult:
        return TurnResult(True, [TextBlock("ok")], [TextBlock("next")])

    def is_finished(self) -> bool:
        return False


class PersistenceTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.built = 0

    def tearDown(self):
        os.unlink(self.db_path)

    def _factory(self, partition_id, user_id):
        """Модель пересборки: генератор отдаёт свежую сессию полного словаря."""
        self.built += 1
        return WordsSession(dict(WORDS))

    def _store(self, ttl_seconds=1800, factory=None):
        return SessionStore(ttl_seconds, repo=self.repo,
                            task_factory=factory or self._factory)


# ---------- Снимок самого задания ----------

class WordsSessionStateTests(unittest.TestCase):
    def test_roundtrip_preserves_progress(self):
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        task.submit(task._current)                 # одно слово отгадано
        snapshot = task.state()

        revived = WordsSession(dict(WORDS))        # свежий полный словарь
        revived.restore(snapshot)
        self.assertEqual(revived._remaining, task._remaining)
        self.assertEqual(len(revived._remaining), len(WORDS) - 1)
        self.assertEqual(revived._current, task._current)
        self.assertEqual(revived._last, task._last)

    def test_total_comes_from_snapshot_not_from_remainder(self):
        # _total — знаменатель прогресса и размер окна антиповтора; пересчёт
        # по остатку сжимал бы окно с каждым отгаданным словом.
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        task.submit(task._current)
        revived = WordsSession({"cat": "кот"})
        revived.restore(task.state())
        self.assertEqual(revived._total, len(WORDS))

    def test_tolerant_flag_survives(self):
        task = WordsSession(dict(WORDS), tolerant=True)
        revived = WordsSession(dict(WORDS))
        revived.restore(task.state())
        self.assertTrue(revived.tolerant)

    def test_current_word_gone_from_dictionary_does_not_break_restore(self):
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        snapshot = task.state()
        snapshot["remaining"].pop(snapshot["current"])
        revived = WordsSession(dict(WORDS))
        revived.restore(snapshot)
        self.assertIsNone(revived._current)

    def test_base_class_default_is_not_serializable(self):
        self.assertIsNone(_OpaqueTask().state())
        with self.assertRaises(NotImplementedError):
            _OpaqueTask().restore({})


# ---------- Repository ----------

class RepositorySessionTests(PersistenceTestBase):
    def test_save_load_delete_roundtrip(self):
        self.repo.save_interactive_session("s-1", 7, "alla", {"a": 1})
        row = self.repo.load_interactive_session("s-1")
        self.assertEqual(row["partition_id"], 7)
        self.assertEqual(row["user_id"], "alla")
        self.assertEqual(row["state"], {"a": 1})
        self.repo.delete_interactive_session("s-1")
        self.assertIsNone(self.repo.load_interactive_session("s-1"))

    def test_save_is_upsert(self):
        self.repo.save_interactive_session("s-1", 7, "alla", {"n": 1})
        self.repo.save_interactive_session("s-1", 7, "alla", {"n": 2})
        self.assertEqual(self.repo.load_interactive_session("s-1")["state"],
                         {"n": 2})
        self.assertEqual(self.repo.count_interactive_sessions(), 1)

    def test_corrupt_state_reads_as_empty_not_as_crash(self):
        self.repo.save_interactive_session("s-1", 7, None, {"n": 1})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE interactive_sessions SET state = '{не json'")
            conn.commit()
        self.assertEqual(self.repo.load_interactive_session("s-1")["state"], {})

    def test_sweep_removes_only_stale(self):
        self.repo.save_interactive_session("fresh", 1, None, {})
        self.repo.save_interactive_session("stale", 1, None, {})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE interactive_sessions SET updated_at = 100 "
                         "WHERE session_id = 'stale'")
            conn.commit()
        self.assertEqual(self.repo.sweep_interactive_sessions(1000), 1)
        self.assertIsNotNone(self.repo.load_interactive_session("fresh"))
        self.assertIsNone(self.repo.load_interactive_session("stale"))


# ---------- Стор ----------

class SessionStoreTests(PersistenceTestBase):
    def test_create_persists_snapshot(self):
        store = self._store()
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        sid = store.create(task, partition_id=42, user_id="alla")
        row = self.repo.load_interactive_session(sid)
        self.assertEqual(row["partition_id"], 42)
        self.assertEqual(row["user_id"], "alla")
        self.assertEqual(row["state"]["current"], task._current)

    def test_second_process_continues_the_same_session(self):
        """Главный сценарий: ход приходит в другой процесс."""
        first = self._store()
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        task.submit(task._current)                 # одно слово отгадано
        sid = first.create(task, partition_id=42, user_id="alla")
        first.save(sid)

        second = self._store()                     # «другой процесс»
        self.assertNotIn(sid, second._items)
        revived = second.get(sid)
        self.assertIsNotNone(revived)
        self.assertEqual(revived._remaining, task._remaining)
        self.assertEqual(revived._current, task._current)
        self.assertEqual(self.built, 1, "пересобрано ровно один раз")

        # И дальше сессия идёт как обычная: второй get попадает уже в кеш.
        second.get(sid)
        self.assertEqual(self.built, 1)

    def test_snapshot_does_not_lag_a_turn_behind(self):
        store = self._store()
        task = WordsSession(dict(WORDS))
        task.initial_prompt()
        sid = store.create(task, partition_id=42)
        task.submit(task._current)                 # ход СДЕЛАН
        store.save(sid)                            # роутер сохраняет после хода

        revived = self._store().get(sid)
        self.assertEqual(len(revived._remaining), len(WORDS) - 1)

    def test_remove_clears_both_levels(self):
        store = self._store()
        sid = store.create(WordsSession(dict(WORDS)), partition_id=42)
        store.remove(sid)
        self.assertIsNone(self.repo.load_interactive_session(sid))
        self.assertIsNone(self._store().get(sid))

    def test_expired_session_is_not_revived(self):
        store = self._store()
        sid = store.create(WordsSession(dict(WORDS)), partition_id=42)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE interactive_sessions SET updated_at = 100")
            conn.commit()
        self.assertIsNone(self._store().get(sid))
        self.assertIsNone(self.repo.load_interactive_session(sid),
                          "протухшая запись убрана, а не оставлена гнить")

    def test_session_of_deleted_partition_is_dropped(self):
        store = self._store()
        sid = store.create(WordsSession(dict(WORDS)), partition_id=42)
        gone = self._store(factory=lambda pid, uid: None)
        self.assertIsNone(gone.get(sid))
        self.assertIsNone(self.repo.load_interactive_session(sid))

    def test_unknown_session_id_is_just_none(self):
        self.assertIsNone(self._store().get("нет-такой"))

    def test_task_without_snapshot_stays_in_memory_only(self):
        store = self._store()
        sid = store.create(_OpaqueTask(), partition_id=42)
        self.assertIsNotNone(store.get(sid), "в своём процессе живёт")
        self.assertIsNone(self.repo.load_interactive_session(sid))
        self.assertIsNone(self._store().get(sid), "в другом — нет, и это честно")

    def test_store_without_repo_is_plain_in_memory(self):
        store = SessionStore()
        self.assertFalse(store.durable)
        sid = store.create(WordsSession(dict(WORDS)), partition_id=42)
        self.assertIsNotNone(store.get(sid))
        self.assertFalse(store.save(sid))

    def test_stats_reports_both_levels(self):
        store = self._store()
        store.create(WordsSession(dict(WORDS)), partition_id=42)
        stats = store.stats()
        self.assertEqual(stats["alive"], 1)
        self.assertEqual(stats["stored"], 1)
        self.assertTrue(stats["durable"])

    def test_persist_failure_does_not_break_the_turn(self):
        """Персист — улучшение, а не условие работы."""
        class BrokenRepo:
            def save_interactive_session(self, *a, **kw):
                raise RuntimeError("БД недоступна")

            def load_interactive_session(self, sid):
                return None

            def sweep_interactive_sessions(self, older_than):
                return 0

        store = SessionStore(repo=BrokenRepo(), task_factory=self._factory)
        # assertLogs заодно глушит вывод намеренного падения в отчёт тестов.
        with self.assertLogs("generator_service.session_store", "ERROR"):
            sid = store.create(WordsSession(dict(WORDS)), partition_id=42)
        self.assertIsNotNone(store.get(sid), "сессия в памяти жива")


if __name__ == "__main__":
    unittest.main()
