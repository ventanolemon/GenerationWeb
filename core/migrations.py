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
import uuid
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
    # NB: пользовательские FK — TEXT (логин-строка, канонический id, единый с
    # десктопом X-User-Id и sync-путём): attempts/devices.user_id, а также
    # групповые created_by/user_id/teacher_id/assigned_by. Ранее групповые
    # были INTEGER (ссылались на users.id) — сведены к логину в _m003 вместе
    # с seed'ом групп из users."group".
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            created_by  TEXT,
            created_at  REAL    NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL,
            user_id  TEXT    NOT NULL,
            PRIMARY KEY (group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS teacher_groups (
            teacher_id TEXT    NOT NULL,
            group_id   INTEGER NOT NULL,
            PRIMARY KEY (teacher_id, group_id)
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            partition_id INTEGER NOT NULL,
            group_id     INTEGER NOT NULL,
            assigned_by  TEXT,
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
        -- contour_jobs / corpus_records здесь СОЗНАТЕЛЬНО не создаются:
        -- владелец их схемы — contour_service/migrations/001_contour.sql.
        -- Ядро эти таблицы не читает и не пишет, а «скелетная» копия молча
        -- выигрывала гонку CREATE TABLE IF NOT EXISTS и ломала contour_service
        -- (no such column: description). Уборка старых копий — миграция 004.
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


# ---------- Миграция 003: группы на логине + seed из users."group" ----------

def _m003_groups_from_labels(conn: sqlite3.Connection) -> None:
    """
    Свести групповые FK к логину-строке (канонический id) и связать
    структурные группы с уже существующими данными.

    Типы: для свежих БД групповые FK создаёт _m001 сразу как TEXT; на старых
    INTEGER-БД SQLite хранит логин-строку по type-affinity (нечисловой текст
    остаётся текстом), а реальных данных в групповых таблицах нет — они не
    были подключены ни к одному сервису. Пересборка таблиц не нужна.

    Seed: свободный `users."group"` — это когорта, которую студент указал при
    регистрации. Здесь она становится настоящей структурной группой
    (`groups` + `group_members`), чтобы существующие пользователи сразу
    оказались в группах, а не требовали ручного перезаполнения. Дальше
    источник истины членства — `group_members`; `users."group"` остаётся
    самоописанием, и seed держит их согласованными (имя группы = метка).
    Repository.create_user поддерживает эту связь для новых регистраций.
    Идемпотентно: группа ищется по имени, членство — INSERT OR IGNORE.
    """
    if not _table_exists(conn, "users") or not _table_exists(conn, "groups"):
        return
    labels = conn.execute(
        'SELECT DISTINCT "group" FROM users '
        'WHERE "group" IS NOT NULL AND "group" <> ""'
    ).fetchall()
    now = time.time()
    for (label,) in labels:
        row = conn.execute(
            "SELECT id FROM groups WHERE name = ?", (label,)
        ).fetchone()
        if row:
            gid = row[0]
        else:
            cur = conn.execute(
                "INSERT INTO groups (name, created_by, created_at) "
                "VALUES (?, NULL, ?)",
                (label, now),
            )
            gid = cur.lastrowid
        for (login,) in conn.execute(
            'SELECT login FROM users WHERE "group" = ?', (label,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO group_members (group_id, user_id) "
                "VALUES (?, ?)",
                (gid, login),
            )


# ---------- Миграция 004: таблицы контура — единственный владелец ----------

# Колонки, по наличию которых узнаётся канон contour_service (их не было в
# скелетной копии, которую до этой миграции создавала _m001).
_CANON_MARKER = {"contour_jobs": "description", "corpus_records": "job_id"}


def _m004_drop_shadow_contour_tables(conn: sqlite3.Connection) -> None:
    """
    Убрать «скелетные» contour_jobs/corpus_records, созданные ранней _m001.

    Схему этих таблиц описывает contour_service/migrations/001_contour.sql, и
    там она богаче: description, constraints, result_probe, critic, error,
    locked_by/locked_at, FK corpus_records→contour_jobs и UNIQUE-индекс
    дедупа (kind, graph_hash). Обе стороны создавали таблицы через
    CREATE TABLE IF NOT EXISTS, поэтому выигрывал тот, кто открыл файл
    первым: если это было ядро, contour_service падал на первом же enqueue
    («table contour_jobs has no column named description»).

    Ядро эти таблицы не читает и не пишет — значит владелец один,
    contour_service. Здесь просто освобождаем имена, чтобы его миграция
    отработала на чистом месте.

    Данные не теряются: непустая скелетная таблица переименовывается в
    *_legacy_001 (её нельзя было наполнить контуром, но БД пользователя мы
    не удаляем молча); пустая — удаляется.
    """
    for table in ("corpus_records", "contour_jobs"):   # сначала зависимая
        if not _table_exists(conn, table):
            continue
        if _has_column(conn, table, _CANON_MARKER[table]):
            continue                                   # уже канон — не трогаем
        rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if rows:
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy_001")
        else:
            conn.execute(f"DROP TABLE {table}")
    # индекс скелетной копии уезжает вместе с таблицей, но на всякий случай
    conn.execute("DROP INDEX IF EXISTS ix_corpus_graph_hash")


# ---------- Миграция 005: индексы горячих путей ----------

def _m005_hot_path_indexes(conn: sqlite3.Connection) -> None:
    """
    Индексы под фактические запросы сервисов. До неё EXPLAIN QUERY PLAN давал
    SCAN на всех четырёх:

      * attempts(partition_id)   — выборка аналитики (analytics_api._load);
      * attempts(assignment_id)  — прогресс по домашке;
      * group_members(user_id)   — «мои группы» (PK (group_id,user_id) не
                                   помогает при поиске по второму столбцу);
      * assignments(group_id)    — домашки группы;
      * assignments(assigned_by) — домашки преподавателя;
      * teacher_groups(group_id) — кто ведёт группу (та же беда с PK).
    """
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS ix_attempts_partition
            ON attempts(partition_id);
        CREATE INDEX IF NOT EXISTS ix_attempts_assignment
            ON attempts(assignment_id);
        CREATE INDEX IF NOT EXISTS ix_group_members_user
            ON group_members(user_id);
        CREATE INDEX IF NOT EXISTS ix_assignments_group
            ON assignments(group_id);
        CREATE INDEX IF NOT EXISTS ix_assignments_author
            ON assignments(assigned_by);
        CREATE INDEX IF NOT EXISTS ix_teacher_groups_group
            ON teacher_groups(group_id);
    """)


# ---------- Миграция 006: выдачи предметов преподавателям ----------

def _m006_subject_grants(conn: sqlite3.Connection) -> None:
    """
    Схема под docs/subject_grants.md (репозиторий Generator): админ раздаёт
    преподавателям доступ к предметам, преподаватель видит в витрине только
    выданные.

    Три объекта, каждый — по прямому требованию документа:

    1. `subject_grants` — сама выдача. Ключ — ЛОГИН, не числовой users.id:
       логин уже канонический идентификатор во всей системе (групповые FK
       после 003, заголовок X-User-Id, core.session десктопа), и заводить
       здесь второй вид ключа значило бы джойнить на каждом authz-чеке.
       Тип granted_at — REAL (epoch), как у всех остальных времён в этой
       схеме; в целевом Postgres это timestamptz.

    2. `app_settings` — умолчание `default_subject_access` ('all'|'none').
       Именно настройка, а не константа: строгий режим в день выкатки
       оставил бы всех преподавателей с пустым экраном, пока админ не прошёл
       по списку. Таблица общего вида, потому что вторая серверная настройка
       появится раньше, чем понадобится вторая таблица.

    3. `users.scope_version` — счётчик scope-эпохи. Курсорный pull не умеет
       в изменение прав (выдали — версия строки старая, курсор её прошёл;
       отозвали — версия не менялась вовсе), поэтому изменение выдач само
       становится событием синхронизации: клиент присылает известную ему
       эпоху, сервер при расхождении отдаёт полный набор и клиент подчищает
       лишнее. Стартовое значение 1, а НЕ 0: клиент, который эпохи ещё не
       знает, шлёт 0 — так он гарантированно получает пересборку на первом
       же pull, вместо того чтобы совпасть с сервером по случайности нуля.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subject_grants (
            teacher_login TEXT    NOT NULL
                REFERENCES users(login) ON DELETE CASCADE,
            subject_id    INTEGER NOT NULL
                REFERENCES Subjects(id) ON DELETE CASCADE,
            granted_by    TEXT    NOT NULL DEFAULT '',
            granted_at    REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (teacher_login, subject_id)
        );
        -- «кому выдан этот предмет» — обратный обход PK не покрывает.
        CREATE INDEX IF NOT EXISTS ix_subject_grants_subject
            ON subject_grants(subject_id);
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
    """)
    if not _table_exists(conn, "users"):
        return                       # users создаёт 001; порядок гарантирован
    _add_column_if_missing(conn, "users", "scope_version",
                           "INTEGER NOT NULL DEFAULT 1")
    # ALTER ... DEFAULT 1 уже проставил единицу существующим строкам; UPDATE
    # страхует случай, когда колонку успела добавить более ранняя копия кода.
    conn.execute(
        "UPDATE users SET scope_version = 1 "
        "WHERE scope_version IS NULL OR scope_version < 1"
    )


# ---------- Миграция 007: интерактивные сессии вне памяти процесса ----------

def _m007_interactive_sessions(conn: sqlite3.Connection) -> None:
    """
    Состояние интерактивной сессии в БД, а не в dict процесса.

    До этой миграции живые `InteractiveTask` лежали в
    `generator_service/session_store.py` — in-memory, «по одному инстансу на
    процесс uvicorn'а» (там это честно оговорено). Пока инстанс один, всё
    работает; за балансировщиком второй ход той же сессии приходит в другой
    процесс и не находит её. Это же ограничение делает невозможным
    перезапуск сервиса без потери всех активных тренажёров.

    Здесь — общее хранилище: сессия описывается партицией (из неё
    пересобирается генератор), владельцем (у тренажёра слов от него зависит
    межсессионная статистика) и сериализованным состоянием. Само состояние —
    JSON-текст, потому что его формат принадлежит конкретному типу задания
    (`InteractiveTask.state()`), а не схеме БД: ядро тут хранилище, а не
    интерпретатор.

    Владелец таблицы — ядро, как у всех таблиц, к которым ходит Repository
    (единственная точка доступа к SQLite; урок миграции 004 — у таблицы один
    владелец). `updated_at` вынесен в индекс: по нему идёт вычистка
    протухших сессий, и это единственный её запрос.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interactive_sessions (
            session_id   TEXT PRIMARY KEY,
            partition_id INTEGER NOT NULL,
            user_id      TEXT,
            state        TEXT NOT NULL DEFAULT '{}',
            created_at   REAL NOT NULL DEFAULT 0,
            updated_at   REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_interactive_sessions_updated
            ON interactive_sessions(updated_at);
    """)


# ---------- Миграция 008: публичный API (ключи приложений, квоты, id) ----------

def _m008_public_api(conn: sqlite3.Connection) -> None:
    """
    Схема под docs/architecture/public_api.md, этапы 1–3.

    **Приложение — не пользователь.** У ключа нет ФИО, группы и роли; у него
    есть владелец, скоуп и квота. Поэтому отдельные таблицы, а не запись в
    `users`: попытка втиснуть их туда завела бы «пользователей», которых
    нельзя пустить ни в один существующий эндпоинт.

    **Ключ хранится хэшем**, как пароль, — утечка дампа не должна отдавать
    рабочие ключи. Но хэш БЫСТРЫЙ (sha256), в отличие от пользовательских
    паролей на pbkdf2, и это не оплошность: ключ — 256 бит машинной
    случайности, перебор невозможен независимо от скорости хэша, а
    проверять его приходится на КАЖДОМ запросе. Медленный KDF здесь
    оплачивал бы несуществующую угрозу временем ответа. Рядом лежит
    `prefix` — первые символы открытым текстом, чтобы владелец узнавал свой
    ключ в списке, не восстанавливая его.

    **Публичные id.** Наружу нельзя отдавать первичные ключи: перенумеруется
    таблица — сломаются все интеграции, а обещание стабильности `id` придётся
    держать вечно. `public_id` — отдельный стабильный uuid; существующим
    строкам он проставляется здесь, новым — лениво при первом обращении
    публичного API (иначе пришлось бы править все пути вставки ради поля,
    нужного одному потребителю).

    **Учёт вызовов** — счётчик на (клиент, день). Не журнал каждого вызова:
    для квоты нужна сумма, а журнал на этом объёме — это гигабайты ради
    одного `SELECT COUNT(*)`. Журнал появится, когда появится тарификация,
    и это будет отдельная таблица с другим сроком жизни.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_clients (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            owner_login  TEXT,
            status       TEXT    NOT NULL DEFAULT 'active',
            daily_quota  INTEGER NOT NULL DEFAULT 1000,
            created_at   REAL    NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            key_hash        TEXT    PRIMARY KEY,
            client_id       INTEGER NOT NULL
                REFERENCES api_clients(id) ON DELETE CASCADE,
            kind            TEXT    NOT NULL DEFAULT 'server',
            prefix          TEXT    NOT NULL DEFAULT '',
            allowed_origins TEXT    NOT NULL DEFAULT '',
            created_at      REAL    NOT NULL DEFAULT 0,
            revoked_at      REAL
        );
        CREATE INDEX IF NOT EXISTS ix_api_keys_client ON api_keys(client_id);
        -- Явная выдача предмета КЛЮЧУ: та же механика, что выдача
        -- преподавателю (subject_grants), но субъект другой. Пустой набор =
        -- клиенту доступны все встроенные предметы (owner IS NULL) и только
        -- они; авторский контент наружу без явного решения не уходит.
        CREATE TABLE IF NOT EXISTS api_client_subjects (
            client_id  INTEGER NOT NULL
                REFERENCES api_clients(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL
                REFERENCES Subjects(id) ON DELETE CASCADE,
            PRIMARY KEY (client_id, subject_id)
        );
        CREATE TABLE IF NOT EXISTS api_usage (
            client_id INTEGER NOT NULL,
            day       TEXT    NOT NULL,
            calls     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (client_id, day)
        );
    """)
    for table in ("Subjects", "Partitions"):
        if not _table_exists(conn, table):
            continue
        _add_column_if_missing(conn, table, "public_id", "TEXT")
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table.lower()}_public_id "
            f"ON {table}(public_id) WHERE public_id IS NOT NULL"
        )
        for (row_id,) in conn.execute(
            f"SELECT id FROM {table} WHERE public_id IS NULL"
        ).fetchall():
            conn.execute(
                f"UPDATE {table} SET public_id = ? WHERE id = ?",
                (str(uuid.uuid4()), row_id),
            )


# Порядок применения. Добавлять новые кортежами (version, name, fn).
MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "rbac_foundation", _m001_rbac_foundation),
    (2, "sync_protocol", _m002_sync_protocol),
    (3, "groups_from_labels", _m003_groups_from_labels),
    (4, "drop_shadow_contour_tables", _m004_drop_shadow_contour_tables),
    (5, "hot_path_indexes", _m005_hot_path_indexes),
    (6, "subject_grants", _m006_subject_grants),
    (7, "interactive_sessions", _m007_interactive_sessions),
    (8, "public_api", _m008_public_api),
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
