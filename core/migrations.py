"""
Версионированные миграции схемы БД.

Проект не имеет Alembic, а схему теперь надо развивать управляемо (RBAC,
владение контентом, sync-колонки, таблицы контура). Этот модуль — минимальный
раннёр: таблица `schema_migrations` фиксирует применённые версии, список
`MIGRATIONS` задаёт порядок. Каждая миграция — функция(conn)->None; раннёр
применяет непринятые по одной и записывает версию. Идемпотентно: повторный
запуск — no-op.

Диалект — SQLite (текущий движок веб-сервиса и десктопа). Схема совместима по
смыслу с целевым Postgres из docs/architecture/rbac_and_data_model.md: типы
INTEGER/TEXT/REAL переносятся напрямую, JSON-поля лежат как TEXT (в Postgres —
JSONB), автоинкремент id → BIGSERIAL/identity. Смена движка на Postgres —
отдельный инфраструктурный шаг, не входит в эту миграцию.
"""

from __future__ import annotations
import sqlite3
import time
from typing import Callable


# ---------- Вспомогательные ----------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, typedef: str
) -> None:
    if _table_exists(conn, table) and not _has_column(conn, table, column):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {typedef}')


# ---------- Миграция 001: фундамент RBAC ----------

def _m001_rbac_foundation(conn: sqlite3.Connection) -> None:
    # --- users: числовой id, роль, format-tagged password_hash ---
    if not _table_exists(conn, "users"):
        # Свежая БД: создаём сразу в целевой форме. login остаётся PRIMARY KEY
        # (аутентификация по логину не ломается — это фаза «expand»); числовой
        # id — цель для внешних ключей новых таблиц.
        conn.execute(
            'CREATE TABLE users ('
            '  login TEXT PRIMARY KEY,'
            '  id INTEGER,'
            '  password TEXT NOT NULL DEFAULT "",'
            '  password_hash TEXT NOT NULL DEFAULT "",'
            '  role TEXT NOT NULL DEFAULT "student",'
            '  FIO TEXT NOT NULL DEFAULT "",'
            '  "group" TEXT NOT NULL DEFAULT "",'
            '  email TEXT NOT NULL DEFAULT "",'
            '  about TEXT NOT NULL DEFAULT "",'
            '  avatar_color TEXT NOT NULL DEFAULT "",'
            '  created_at REAL NOT NULL DEFAULT 0'
            ')'
        )
    else:
        # Существующая БД (десктопная/веб): расширяем колонками. Профильные
        # колонки могли быть добавлены прежним ensure_users_table — проверяем.
        for col, typedef in [
            ("id",            "INTEGER"),
            ("password",      'TEXT NOT NULL DEFAULT ""'),
            ("password_hash", 'TEXT NOT NULL DEFAULT ""'),
            ("role",          'TEXT NOT NULL DEFAULT "student"'),
            ("email",         'TEXT NOT NULL DEFAULT ""'),
            ("about",         'TEXT NOT NULL DEFAULT ""'),
            ("avatar_color",  'TEXT NOT NULL DEFAULT ""'),
            ("created_at",    "REAL NOT NULL DEFAULT 0"),
        ]:
            _add_column_if_missing(conn, "users", col, typedef)

    # Backfill числового id из rowid (стабилен, уникален, монотонен).
    conn.execute("UPDATE users SET id = rowid WHERE id IS NULL")
    # Перенос унаследованных паролей в password_hash с пометкой legacy:.
    # Содержимое — plaintext (десктоп) или sha256(login:password) (веб);
    # passwords.verify_password разбирает оба и просит апгрейд при входе.
    conn.execute(
        "UPDATE users SET password_hash = 'legacy:' || password "
        "WHERE (password_hash = '' OR password_hash IS NULL) "
        "  AND password IS NOT NULL AND password <> ''"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_id ON users(id)")

    # --- Subjects: владение + sync-колонки ---
    # owner_user_id — логин-строка (канонический id, единый с десктопом
    # core.session.Session и заголовком X-User-Id). Ранее INTEGER; TEXT,
    # чтобы владельцем выступал логин, а не rowid users.id.
    _add_column_if_missing(conn, "Subjects", "owner_user_id", "TEXT")
    _add_column_if_missing(conn, "Subjects", "row_version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "Subjects", "updated_at", "REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "Subjects", "deleted_at", "REAL")

    # --- Partitions: sync-колонки (владение наследуется от предмета) ---
    _add_column_if_missing(conn, "Partitions", "row_version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "Partitions", "updated_at", "REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "Partitions", "deleted_at", "REAL")

    # --- Новые таблицы (схема; логику наполняют последующие фазы/сервисы) ---
    # NB: attempts.user_id и devices.user_id — TEXT (логин-строка, единый с
    # десктопом X-User-Id), т.к. это sync-путь: устройство шлёт логин, а не
    # числовой users.id. Групповые FK (groups/teacher_groups/assignments/
    # group_members) остаются INTEGER — они вне sync-пути и приводятся к
    # логину в задаче про группы.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            created_by  INTEGER,
            created_at  REAL    NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            PRIMARY KEY (group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS teacher_groups (
            teacher_id INTEGER NOT NULL,
            group_id   INTEGER NOT NULL,
            PRIMARY KEY (teacher_id, group_id)
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            partition_id INTEGER NOT NULL,
            group_id     INTEGER NOT NULL,
            assigned_by  INTEGER,
            due_at       REAL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            client_uuid   TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            partition_id  INTEGER NOT NULL,
            assignment_id INTEGER,
            payload       TEXT NOT NULL DEFAULT '',
            correct       INTEGER,
            device_id     TEXT,
            created_at    REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS devices (
            device_id          TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL,
            refresh_token_hash TEXT NOT NULL DEFAULT '',
            last_sync_at       REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS contour_jobs (
            id           TEXT PRIMARY KEY,
            created_by   TEXT,
            subject_id   INTEGER,
            status       TEXT NOT NULL DEFAULT 'queued',
            rounds       TEXT NOT NULL DEFAULT '[]',
            result_graph TEXT,
            created_at   REAL NOT NULL DEFAULT 0,
            updated_at   REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS corpus_records (
            id         TEXT PRIMARY KEY,
            job_id     TEXT,
            kind       TEXT NOT NULL,
            record     TEXT NOT NULL,
            graph_hash TEXT,
            created_at REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_corpus_graph_hash ON corpus_records(graph_hash);
        CREATE INDEX IF NOT EXISTS ix_attempts_user     ON attempts(user_id);
        CREATE INDEX IF NOT EXISTS ix_partitions_subject ON Partitions(subject_id);
    """)


# ---------- Миграция 002: offline-sync ----------

def _m002_sync_protocol(conn: sqlite3.Connection) -> None:
    """
    Схема под offline_sync_protocol.md. Сами sync-колонки (row_version/
    updated_at/deleted_at), devices и attempts(client_uuid PK) создала 001 —
    здесь доводка семантики курсора:

    1. Курсор pull = «максимальный полученный row_version на ТИП сущности»,
       значит row_version обязан быть глобально монотонным per-таблица
       (в Postgres — sequence). По-строчный `+1` даёт неуникальные версии,
       и страница, разрезанная посреди «связки» одинаковых версий, теряет
       записи (`WHERE row_version > cursor` перепрыгнет хвост связки).
       Backfill: развязать существующие версии в уникальную возрастающую
       нумерацию (стабильный порядок: старая версия, затем id). Дальше
       уникальность держит запись через MAX+1 (см. Repository).
    2. Индексы под диф-скан `row_version > cursor`.
    """
    for table in ("Subjects", "Partitions"):
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT id FROM {table} ORDER BY row_version, id"
        ).fetchall()
        for i, (row_id,) in enumerate(rows, start=1):
            conn.execute(
                f"UPDATE {table} SET row_version = ? WHERE id = ?",
                (i, row_id),
            )
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS ix_subjects_row_version
            ON Subjects(row_version);
        CREATE INDEX IF NOT EXISTS ix_partitions_row_version
            ON Partitions(row_version);
        CREATE INDEX IF NOT EXISTS ix_attempts_device ON attempts(device_id);
    """)


# Порядок применения. Добавлять новые кортежами (version, name, fn).
MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "rbac_foundation", _m001_rbac_foundation),
    (2, "sync_protocol", _m002_sync_protocol),
]


# ---------- Раннёр ----------

def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  applied_at REAL NOT NULL"
        ")"
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    _ensure_migrations_table(conn)
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Применить все непринятые миграции по порядку. Вернуть имена применённых."""
    done = applied_versions(conn)
    applied: list[str] = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (?, ?, ?)",
            (version, name, time.time()),
        )
        conn.commit()
        applied.append(name)
    return applied
