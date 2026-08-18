"""
База в репозитории: она попадает в коммит, значит должна быть пригодна.

Зачем проверка
--------------
`resources/users_database.db` лежит в репозитории и обновляется вместе с
кодом. При этом любой запуск проекта из рабочей копии её МЕНЯЕТ: слой
доступа заводит служебные таблицы и прогоняет миграции. Дальше файл
уходит в коммит двоичной строкой «Bin … bytes», в которой не видно
ничего.

Это происходило дважды за одну сессию работы: сначала разбор дефекта
завёл две пустые таблицы, потом скрипт замера открыл базу напрямую. Оба
раза содержания в изменении не было. Тот же путь ведёт и к файлу, который
на другой машине не откроется, — и незакрытый отчёт «database disk image
is malformed» у нас уже есть (десктоп).

Что проверяется и чего НЕ проверяется
-------------------------------------
Проверяется пригодность файла: целостность, отсутствие хвостов журнала
рядом и то, что каждый кодовый раздел открывается.

**Журнал здесь `wal`, и это отличается от десктопа**, где WAL запрещён.
Разница осознанная: у десктопа файл — ресурс поставки, копируемый
пользователю, и WAL там означает неполный файл без соседнего `-wal`.
Здесь файл — рабочая база разработки. Опасен не сам режим, а хвост
журнала, попавший в коммит; на него проверка и стоит.

Запуск:
    python -m unittest core.test_shipped_database
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from const import DB_PATH


class DatabaseFileTests(unittest.TestCase):

    def setUp(self):
        if not Path(DB_PATH).exists():
            self.skipTest("базы нет в этой сборке")
        # Работаем с КОПИЕЙ: проверка не имеет права стать ещё одним
        # писателем в файл, который сама и защищает.
        self.copy = tempfile.mktemp(suffix=".db")
        shutil.copyfile(DB_PATH, self.copy)
        self.addCleanup(
            lambda: os.path.exists(self.copy) and os.unlink(self.copy))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.copy)
        self.addCleanup(conn.close)
        return conn

    def test_structure_is_intact(self):
        self.assertEqual(
            self._connect().execute("PRAGMA integrity_check").fetchone()[0],
            "ok")

    def test_no_journal_leftovers_next_to_it(self):
        """
        Хвост журнала, попавший в коммит, — прямой путь к базе, которая
        на другой машине не откроется.
        """
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(хвост=suffix):
                self.assertFalse(
                    Path(str(DB_PATH) + suffix).exists(),
                    f"рядом с базой лежит {suffix}: в таком состоянии "
                    f"коммитить нельзя")

    def test_it_opens_and_carries_what_the_code_expects(self):
        conn = self._connect()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"Subjects", "Partitions", "users",
                              "attempts", "schema_migrations"}, tables)

    def test_pending_migrations_apply_cleanly(self):
        """
        Проверяется не «все миграции уже применены» — база в репозитории
        отстаёт от кода намеренно, недостающие применяются при первом
        запуске, — а то, что применяются они БЕЗ ОШИБКИ и повторный
        прогон пуст.

        Первая редакция теста требовала, чтобы база была уже
        мигрирована, и падала на непринятой миграции 15. Требование было
        неверным: коммитить пре-мигрированную базу никто не обязан.
        """
        from core.migrations import MIGRATIONS, applied_versions, run_migrations

        conn = self._connect()
        run_migrations(conn)
        conn.commit()
        self.assertEqual(run_migrations(conn), [],
                         "повторный прогон применил миграции")
        expected = {version for version, _name, _fn in MIGRATIONS}
        self.assertEqual(expected - applied_versions(conn), set())

    def test_every_code_partition_has_a_generator(self):
        """
        Раздел с `constracted = 0` заявляет, что его обслуживает КОД.
        Если кода нет, обращение к разделу даёт отказ — так в поставке
        десктопа обнаружился раздел «конструктор» предмета Физика.
        """
        import bootstrap
        from const import WORDS_DIR
        from core import Repository

        repo = Repository(self.copy)
        bootstrap.sync_database(repo, WORDS_DIR)
        registry = bootstrap.build_registry(repo, WORDS_DIR)

        unserved = []
        for subject in repo.list_subjects():
            for part in repo.list_partitions_for_subject(subject.id):
                if part.constracted == 0 and not registry.has(part.id):
                    unserved.append((part.id, part.name, subject.name))
        self.assertEqual(unserved, [])


if __name__ == "__main__":
    unittest.main()
