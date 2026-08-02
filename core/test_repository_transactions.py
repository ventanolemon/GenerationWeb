"""
Соединение и транзакции Repository.

До этого каждый метод открывал СВОЁ соединение и коммитил сам, а
многошаговые операции слоем выше брали приватное `_connect()` с `# noqa` —
то есть атомарности у них не было вовсе: между проверкой и записью могло
произойти что угодно. Здесь закрепляем новое поведение:

  * соединение одно на поток и переиспользуется;
  * `transaction()` публичная и вложенная — внутренний вызов присоединяется
    к открытой транзакции, а не коммитит её половину;
  * откат при исключении честный, в том числе для работы, сделанной
    вложенными вызовами;
  * потоки друг другу не мешают.

Запуск: python -m unittest core.test_repository_transactions -v
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core import admin_api  # noqa: E402
from core.repository import Repository  # noqa: E402


class TransactionTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def _logins(self) -> set[str]:
        """Читаем ОТДЕЛЬНЫМ соединением: незафиксированное оно не увидит."""
        with sqlite3.connect(self.db_path) as conn:
            return {r[0] for r in conn.execute("SELECT login FROM users")}


class ConnectionReuseTests(TransactionTestBase):
    def test_same_connection_within_a_thread(self):
        with self.repo.transaction() as first:
            pass
        with self.repo.transaction() as second:
            pass
        self.assertIs(first, second, "соединение переиспользуется, а не "
                                     "открывается на каждый вызов")

    def test_each_thread_gets_its_own(self):
        # sqlite3.Connection не переносится между потоками, а sync-роуты
        # FastAPI работают в пуле потоков.
        seen: dict[str, object] = {}

        def grab(name):
            with self.repo.transaction() as conn:
                seen[name] = conn

        threads = [threading.Thread(target=grab, args=(f"t{i}",))
                   for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(map(id, seen.values()))), 3)

    def test_close_releases_and_reopens(self):
        with self.repo.transaction() as before:
            pass
        self.repo.close()
        with self.repo.transaction() as after:
            pass
        self.assertIsNot(before, after)


class CommitAndRollbackTests(TransactionTestBase):
    def test_work_is_visible_after_the_block(self):
        self.repo.create_user("ivan", "p", "Иван", "")
        self.assertIn("ivan", self._logins())

    def test_exception_rolls_the_whole_block_back(self):
        with self.assertRaises(RuntimeError):
            with self.repo.transaction() as conn:
                conn.execute(
                    "INSERT INTO users (login, role) VALUES ('boom', 'student')")
                raise RuntimeError("что-то пошло не так")
        self.assertNotIn("boom", self._logins())

    def test_nothing_is_visible_until_the_block_ends(self):
        with self.repo.transaction() as conn:
            conn.execute(
                "INSERT INTO users (login, role) VALUES ('pending', 'student')")
            self.assertNotIn("pending", self._logins(),
                             "до фиксации снаружи не видно")
        self.assertIn("pending", self._logins())


class NestingTests(TransactionTestBase):
    def test_inner_block_does_not_commit_the_outer(self):
        # Ровно та поломка, ради которой вложенность и сделана: внутренний
        # вызов раньше коммитил половину чужой работы.
        with self.repo.transaction() as conn:
            conn.execute(
                "INSERT INTO users (login, role) VALUES ('outer', 'student')")
            with self.repo.transaction():
                conn.execute(
                    "INSERT INTO users (login, role) VALUES ('inner', 'student')")
            self.assertEqual(self._logins() & {"outer", "inner"}, set(),
                             "внутренний выход ничего не зафиксировал")
        self.assertEqual(self._logins() & {"outer", "inner"},
                         {"outer", "inner"})

    def test_outer_rollback_undoes_inner_work(self):
        with self.assertRaises(RuntimeError):
            with self.repo.transaction():
                # Обычный метод Repository — он тоже откроет транзакцию,
                # вложенную в эту.
                self.repo.create_user("nested", "p", "Вложенный", "")
                raise RuntimeError("откат")
        self.assertNotIn("nested", self._logins(),
                         "работа вложенного вызова откатилась вместе с внешней")

    def test_depth_returns_to_zero(self):
        with self.repo.transaction():
            with self.repo.transaction():
                pass
        self.assertEqual(getattr(self.repo._local, "depth", 0), 0)

    def test_depth_returns_to_zero_after_error(self):
        with self.assertRaises(ValueError):
            with self.repo.transaction():
                raise ValueError("x")
        self.assertEqual(getattr(self.repo._local, "depth", 0), 0)
        # И следующая транзакция работает как ни в чём не бывало.
        self.repo.create_user("after", "p", "После", "")
        self.assertIn("after", self._logins())


class AtomicMultiStepTests(TransactionTestBase):
    """Многошаговые операции слоем выше стали атомарными."""

    def test_change_role_check_and_write_are_one_transaction(self):
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        before = self.repo.scope_version("alla")

        admin_api.change_role(self.repo, actor_login="root",
                              target_login="alla", new_role="student")
        self.assertEqual(self.repo.get_user_profile("alla").role, "student")
        self.assertEqual(self.repo.scope_version("alla"), before + 1)

    def test_last_admin_guard_leaves_nothing_half_written(self):
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        before = self.repo.scope_version("root")
        with self.assertRaisesRegex(admin_api.AdminActionError, "последнего"):
            admin_api.change_role(self.repo, actor_login="other",
                                  target_login="root", new_role="student")
        # Ни роль, ни эпоха не сдвинулись.
        self.assertEqual(self.repo.get_user_profile("root").role, "admin")
        self.assertEqual(self.repo.scope_version("root"), before)


if __name__ == "__main__":
    unittest.main()
