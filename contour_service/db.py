"""
Подключение к БД контура и применение миграций.

По умолчанию — SQLite-файл монорепо (та же БД, где Subjects/Partitions:
approve пишет партицию в неё же, одна точка истины). Postgres включается
DSN'ом (CONTOUR_PG_DSN) — тогда очередь работает через
FOR UPDATE SKIP LOCKED (см. queue.PostgresJobQueue).

Миграции — плоские SQL-файлы contour_service/migrations/*.sql в
лексикографическом порядке, идемпотентные (IF NOT EXISTS): сложный
версионированный раннер здесь не нужен (ср. core/migrations.py — он про
схему десктопа; таблицы контура аддитивны и живут отдельно).
"""

from __future__ import annotations
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect_sqlite(db_path: "str | Path") -> sqlite3.Connection:
    """Соединение SQLite с включёнными FK и row_factory-словарями."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_migrations(conn) -> list[str]:
    """Применить все SQL-файлы миграций (идемпотентно). Возвращает имена."""
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        if isinstance(conn, sqlite3.Connection):
            conn.executescript(sql)
        else:  # DB-API соединение Postgres: statement-by-statement
            cur = conn.cursor()
            for stmt in _split_statements(sql):
                cur.execute(stmt)
            conn.commit()
        applied.append(path.name)
    return applied


def _split_statements(sql: str) -> list[str]:
    """Разбить SQL-скрипт на statements (по ';' вне строк — DDL простой)."""
    out, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out
