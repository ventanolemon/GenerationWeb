"""
Регрессия: contour_service должен работать на БД, которую первым создало
и мигрировало ядро (core/migrations.py).

Это дефолтная конфигурация: ContourConfig.db_path = const.DB_PATH, то есть
контур по умолчанию садится на ту же SQLite, где живут Subjects/Partitions
и пользователи. Раньше ядро само заводило «скелетные» contour_jobs и
corpus_records через CREATE TABLE IF NOT EXISTS; они выигрывали гонку, и
канонический DDL contour_service молча становился no-op. Первый же enqueue
падал с «table contour_jobs has no column named description», то есть
контур на дефолтных настройках был неработоспособен целиком.

Владелец схемы этих таблиц теперь один — contour_service; ядро их не
создаёт (миграция 004 убирает старые копии).

Запуск без pytest:  python contour_service/tests/test_schema_ownership.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.repository import Repository  # noqa: E402
from core.migrations import run_migrations  # noqa: E402
from contour_service.db import connect_sqlite, apply_migrations  # noqa: E402
from contour_service.queue import SqliteJobQueue, QUEUED  # noqa: E402

# Колонки канонического DDL (contour_service/migrations/001_contour.sql),
# которых не было в скелетной копии ядра.
_CANON_COLS = {
    "description", "constraints", "result_probe", "critic", "error",
    "locked_by", "locked_at",
}


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)          # Repository создаст заново
    return path


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


def test_contour_works_on_core_created_db():
    """Ядро создаёт БД первым — контур всё равно поднимается и принимает джобу."""
    path = _tmp_db()
    try:
        Repository(path)                       # ядро: миграции 001..005
        conn = connect_sqlite(path)
        apply_migrations(conn)                 # контур: свой канонический DDL

        cols = {r[1] for r in conn.execute("PRAGMA table_info(contour_jobs)")}
        assert _CANON_COLS <= cols, f"схема не каноническая, нет: {_CANON_COLS - cols}"

        queue = SqliteJobQueue(conn)
        job_id = queue.enqueue(
            created_by="alla", subject_id=6,
            description="Сила F=ma: случайные массы", constraints={"task_type": "static"},
        )
        job = queue.get(job_id)
        assert job is not None, "джоба не читается после enqueue"
        assert job["status"] == QUEUED, job["status"]
        assert job["description"] == "Сила F=ma: случайные массы"
        assert job["constraints"] == {"task_type": "static"}
        conn.close()
    finally:
        _cleanup(path)


def test_core_does_not_create_contour_tables():
    """Ядро больше не заводит таблицы контура — владелец схемы один."""
    path = _tmp_db()
    try:
        Repository(path)
        with sqlite3.connect(path) as conn:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "contour_jobs" not in tables, "ядро снова создаёт contour_jobs"
        assert "corpus_records" not in tables, "ядро снова создаёт corpus_records"
    finally:
        _cleanup(path)


def test_legacy_skeleton_is_migrated_away():
    """
    БД, уже пострадавшая от старой _m001 (скелетные таблицы записаны, версия
    001 отмечена применённой), чинится миграцией 004 — и контур на ней
    работает. Непустая скелетная таблица не удаляется молча, а уезжает в
    *_legacy_001.
    """
    path = _tmp_db()
    try:
        # Воспроизводим состояние «до фикса»: скелетные таблицы + строка в них.
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE contour_jobs (
                id TEXT PRIMARY KEY, created_by TEXT, subject_id INTEGER,
                status TEXT NOT NULL DEFAULT 'queued',
                rounds TEXT NOT NULL DEFAULT '[]', result_graph TEXT,
                created_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE corpus_records (
                id TEXT PRIMARY KEY, job_id TEXT, kind TEXT NOT NULL,
                record TEXT NOT NULL, graph_hash TEXT,
                created_at REAL NOT NULL DEFAULT 0);
            CREATE INDEX ix_corpus_graph_hash ON corpus_records(graph_hash);
        """)
        conn.execute("INSERT INTO contour_jobs (id, status) VALUES ('old-1', 'queued')")
        conn.commit()
        conn.close()

        Repository(path)                       # прогоняет миграции, включая 004
        conn = connect_sqlite(path)
        apply_migrations(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(contour_jobs)")}
        assert _CANON_COLS <= cols, f"схема не починена, нет: {_CANON_COLS - cols}"

        # Непустая скелетная таблица сохранена под другим именем.
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "contour_jobs_legacy_001" in tables, tables
        kept = conn.execute(
            "SELECT id FROM contour_jobs_legacy_001").fetchall()
        assert [r[0] for r in kept] == ["old-1"], kept
        # Пустая — просто удалена, без легаси-хвоста.
        assert "corpus_records_legacy_001" not in tables, tables

        job_id = SqliteJobQueue(conn).enqueue(
            created_by="alla", subject_id=6, description="после починки")
        assert SqliteJobQueue(conn).get(job_id)["description"] == "после починки"
        conn.close()
    finally:
        _cleanup(path)


def test_corpus_dedup_index_present():
    """UNIQUE(kind, graph_hash) — дедуп корпуса обеспечивает БД, не пост-обработка."""
    path = _tmp_db()
    try:
        Repository(path)
        conn = connect_sqlite(path)
        apply_migrations(conn)
        idx = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "uq_corpus_kind_hash" in idx, idx
        conn.close()
    finally:
        _cleanup(path)


def test_hot_path_indexes_and_pragmas():
    """Миграция 005 закрывает SCAN'ы; соединения ядра включают foreign_keys."""
    path = _tmp_db()
    try:
        repo = Repository(path)
        with repo._connect() as conn:  # noqa: SLF001 — проверяем сам слой данных
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1, \
                "foreign_keys выключён — объявленные REFERENCES не проверяются"
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal", \
                "журнал не WAL — читатели блокируют писателя"
            idx = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")
            }
            need = {
                "ix_attempts_partition", "ix_attempts_assignment",
                "ix_group_members_user", "ix_assignments_group",
                "ix_assignments_author", "ix_teacher_groups_group",
            }
            assert need <= idx, f"нет индексов: {need - idx}"
            # План запроса аналитики больше не полный скан.
            plan = " ".join(
                str(r[-1]) for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT user_id, correct FROM attempts "
                    "WHERE partition_id IN (1,2,3)")
            )
            assert "SCAN attempts" not in plan, plan
    finally:
        _cleanup(path)


_TESTS = [
    test_contour_works_on_core_created_db,
    test_core_does_not_create_contour_tables,
    test_legacy_skeleton_is_migrated_away,
    test_corpus_dedup_index_present,
    test_hot_path_indexes_and_pragmas,
]


def main() -> int:
    failed = 0
    for t in _TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failed}/{len(_TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
