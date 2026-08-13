"""
Хранение попыток (этап 3) — только сервер.

Таблица `attempts` серверная: у десктопа её нет, он отправляет попытки
синком. Поэтому эти тесты живут отдельно от `core.test_scenarios`, который
зеркалится в оба репозитория, — иначе десктопный прогон падал бы на
проверке несуществующей таблицы.

Запуск: python -m unittest core.test_attempt_storage  (из корня монорепо)
"""

import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core.answers import NumberSpec  # noqa: E402
from core.attempts import AttemptRecord, attempts_from_session  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.interactive import Question, SpecSession  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.scenarios import ADAPTIVE, Layer, Scenario, SessionMode  # noqa: E402


def a_session(scenario=None, count=2):
    questions = [
        Question([TextBlock(f"вопрос {i}")], NumberSpec(value=float(i)))
        for i in range(count)
    ]
    return SpecSession(questions, scenario=scenario)


class AttemptStorageTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "db.sqlite")
        self.repo = Repository(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def rows(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM attempts")]
        finally:
            conn.close()

    def records(self, session_id="sid"):
        scenario = Scenario.for_mode(SessionMode.PRACTICE)
        session = a_session(scenario)
        session.submit("0")
        session.submit("1")
        return attempts_from_session(
            session, scenario, session_id=session_id, user_id="ivanov",
            partition_id=42)

    def test_columns_exist(self):
        conn = sqlite3.connect(self.path)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(attempts)")}
        conn.close()
        self.assertLessEqual(
            {"session_mode", "check_mode", "adaptive", "attempts_used",
             "counts_toward_stats"}, columns)

    def test_saving_writes_rows(self):
        self.assertEqual(self.repo.save_attempts(self.records()), 2)
        self.assertEqual(len(self.rows()), 2)

    def test_stored_values_round_trip(self):
        self.repo.save_attempts(self.records())
        row = self.rows()[0]
        self.assertEqual(row["session_mode"], "practice")
        self.assertEqual(row["check_mode"], "soft")
        self.assertEqual(row["adaptive"], 0)
        self.assertEqual(row["counts_toward_stats"], 1)

    def test_repeated_save_does_not_duplicate(self):
        # Повтор запроса не должен удваивать успеваемость.
        self.repo.save_attempts(self.records())
        second = self.repo.save_attempts(self.records())
        self.assertEqual(second, 0)
        self.assertEqual(len(self.rows()), 2)

    def test_different_sessions_do_not_collide(self):
        self.repo.save_attempts(self.records("first"))
        self.repo.save_attempts(self.records("second"))
        self.assertEqual(len(self.rows()), 4)

    def test_empty_list_is_a_no_op(self):
        self.assertEqual(self.repo.save_attempts([]), 0)

    def test_adaptive_flag_is_stored(self):
        scenario = (Scenario.for_mode(SessionMode.PRACTICE)
                    .with_layer(Layer.ASSIGNMENT, {ADAPTIVE: True}))
        session = a_session(scenario, count=1)
        session.submit("0")
        self.repo.save_attempts(attempts_from_session(
            session, scenario, session_id="sid", user_id="u", partition_id=1))
        self.assertEqual(self.rows()[0]["adaptive"], 1)

    def test_legacy_rows_keep_null_mode(self):
        # Строки, записанные до сценариев, честно не знают своего режима.
        # Подставить им какой-нибудь значило бы сделать выдумку
        # неотличимой от факта.
        conn = sqlite3.connect(self.path)
        conn.execute(
            "INSERT INTO attempts (client_uuid, user_id, partition_id, "
            "payload, correct, created_at) VALUES ('old', 'u', 1, '', 1, 0)")
        conn.commit()
        conn.close()
        legacy = [r for r in self.rows() if r["client_uuid"] == "old"][0]
        self.assertIsNone(legacy["session_mode"])

    def test_row_shape_matches_column_order(self):
        record = AttemptRecord(
            client_uuid="x", user_id="u", partition_id=1, correct=True,
            session_mode="practice", check_mode="soft", adaptive=False,
            attempts_used=1)
        self.assertEqual(self.repo.save_attempts([record]), 1)
        self.assertEqual(len(self.rows()), 1)

if __name__ == "__main__":
    unittest.main()
