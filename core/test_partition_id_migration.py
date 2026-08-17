"""
Миграция 015: словари английского переезжают с номера ПО МЕСТУ на номер
ПО ИМЕНИ — вместе со всем, что на них ссылается.

Дефект, ради которого миграция написана, — не гипотеза, а замер живых баз:

    id     сервер (20 словарей)        десктоп (12 словарей)
    1001   complete_vocabulary         complete_words
    1002   complete_words              term_4_complete_vocabulary

Синхронизация переносит разделы ПО НОМЕРУ. Значит, домашнее задание,
выданное на сервере по разделу 1001, открывало на десктопе другой словарь.
Ошибки при этом не возникало нигде: обе стороны считали себя правыми.

Запуск:
    python -m unittest core.test_partition_id_migration
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from core import partition_ids
from core.migrations import run_migrations
from core.repository import Repository


def _database() -> sqlite3.Connection:
    """
    БД со схемой, достаточной для миграций, и предметом «Английский».

    Схему заводит Repository (он и прогоняет миграции при создании) —
    отдельные миграции опираются на базовые таблицы и на голом соединении
    не поднимутся.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    Repository(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR IGNORE INTO Subjects (id, subject_name, pra_subject) "
        "VALUES (2, 'Английский', 'Английский')")
    conn.commit()
    return conn


def _add_legacy_dictionaries(conn: sqlite3.Connection,
                             stems: list[str]) -> dict[str, int]:
    """Разложить словари по СТАРОЙ схеме: 1000 + место в списке."""
    placed: dict[str, int] = {}
    for i, stem in enumerate(sorted(stems)):
        pid = 1000 + i
        conn.execute(
            "INSERT INTO Partitions (id, subject_id, partition_name, "
            " constracted, generation_parametrs, row_version, updated_at) "
            "VALUES (?, 2, ?, 0, '', 1, 0)",
            (pid, f"Английский: {stem}"))
        placed[stem] = pid
    conn.commit()
    return placed


class MigrationTests(unittest.TestCase):

    STEMS = ["complete_words", "unit1_history", "unit2_types"]

    def setUp(self):
        self.conn = _database()
        self.addCleanup(self.conn.close)

    def _ids(self) -> dict[str, int]:
        return {name: pid for pid, name in self.conn.execute(
            "SELECT id, partition_name FROM Partitions WHERE subject_id = 2")}

    def test_dictionaries_move_to_their_name_derived_id(self):
        legacy = _add_legacy_dictionaries(self.conn, self.STEMS)
        self.conn.execute("DELETE FROM schema_migrations WHERE version = 15")
        run_migrations(self.conn)
        ids = self._ids()
        for stem, old in legacy.items():
            with self.subTest(stem=stem):
                self.assertEqual(ids[f"Английский: {stem}"],
                                 partition_ids.english_words_id(stem))
                self.assertNotEqual(ids[f"Английский: {stem}"], old)

    def test_both_sides_agree_on_the_same_dictionary(self):
        """
        То, ради чего всё делалось. Каталоги разной длины — номер один и
        тот же, потому что он больше не зависит от каталога.
        """
        server = ["a_extra", *self.STEMS, "z_extra"]
        desktop = self.STEMS
        on_server = partition_ids.assign(server, partition_ids.ENGLISH_WORDS)
        on_desktop = partition_ids.assign(desktop, partition_ids.ENGLISH_WORDS)
        for stem in self.STEMS:
            with self.subTest(stem=stem):
                self.assertEqual(on_server[stem], on_desktop[stem])

    def test_assignments_and_attempts_follow_the_move(self):
        """
        Выданное задание и накопленные попытки указывают на номер раздела.
        Строка, переехавшая без них, оставила бы задание указывающим в
        пустоту — это хуже исходного дефекта: сломалось бы работавшее.
        """
        legacy = _add_legacy_dictionaries(self.conn, self.STEMS)
        moved = legacy["unit1_history"]
        self.conn.execute(
            "INSERT INTO attempts (client_uuid, user_id, partition_id, "
            " payload, correct, created_at) VALUES ('u-1', 1, ?, '{}', 1, 0)",
            (moved,))
        self.conn.commit()

        self.conn.execute("DELETE FROM schema_migrations WHERE version = 15")
        run_migrations(self.conn)

        expected = partition_ids.english_words_id("unit1_history")
        rows = self.conn.execute(
            "SELECT partition_id FROM attempts").fetchall()
        self.assertEqual([r[0] for r in rows], [expected])

    def test_group_membership_follows_the_move(self):
        legacy = _add_legacy_dictionaries(self.conn, self.STEMS)
        moved = legacy["complete_words"]
        self.conn.execute(
            "INSERT INTO Partitions (subject_id, partition_name, constracted, "
            " generation_parametrs, row_version, updated_at) "
            "VALUES (2, 'Группа со словарём', 2, ?, 1, 0)",
            (json.dumps([{"task_id": moved, "task_name": "словарь"}]),))
        self.conn.commit()

        self.conn.execute("DELETE FROM schema_migrations WHERE version = 15")
        run_migrations(self.conn)

        raw = self.conn.execute(
            "SELECT generation_parametrs FROM Partitions "
            "WHERE partition_name = 'Группа со словарём'").fetchone()[0]
        self.assertEqual(json.loads(raw)[0]["task_id"],
                         partition_ids.english_words_id("complete_words"))

    def test_migration_is_idempotent(self):
        _add_legacy_dictionaries(self.conn, self.STEMS)
        self.conn.execute("DELETE FROM schema_migrations WHERE version = 15")
        run_migrations(self.conn)
        first = sorted(self._ids().values())
        self.assertEqual(run_migrations(self.conn), [])
        self.assertEqual(sorted(self._ids().values()), first)

    def test_rows_outside_the_legacy_band_are_left_alone(self):
        """
        Миграция чинит одну конкретную схему нумерации. Раздел, заведённый
        пользователем, к ней отношения не имеет — его трогать нельзя.
        """
        self.conn.execute(
            "INSERT INTO Partitions (id, subject_id, partition_name, "
            " constracted, generation_parametrs, row_version, updated_at) "
            "VALUES (77, 2, 'Английский: мой раздел', 2, '', 1, 0)")
        self.conn.commit()
        self.conn.execute("DELETE FROM schema_migrations WHERE version = 15")
        run_migrations(self.conn)
        self.assertEqual(self._ids().get("Английский: мой раздел"), 77)


class NameParsingTests(unittest.TestCase):
    """Имя раздела — единственное, что в старой схеме что-то значило."""

    def test_stem_is_recovered_from_the_display_name(self):
        from core.migrations import _english_stem
        self.assertEqual(_english_stem("Английский: unit1_history"),
                         "unit1_history")
        self.assertEqual(
            _english_stem("Английский: term_4_z_sentences_it (предложения)"),
            "term_4_z_sentences_it")

    def test_foreign_names_are_not_touched(self):
        from core.migrations import _english_stem
        self.assertIsNone(_english_stem("Группа"))
        self.assertIsNone(_english_stem("Английский: "))


if __name__ == "__main__":
    unittest.main()
