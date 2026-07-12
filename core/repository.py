"""
Repository — слой доступа к БД.

Все запросы параметризованы (никаких f-строк в SQL).
Все обращения к Subjects/Partitions идут только через этот класс —
никакого `sqlite3.connect(db)` в других файлах.

Subject и Partition — обычные dataclass'ы, безо всякой UI-зависимости.
Им добавлен to_dict() для веб-сериализации в одном стиле с блоками
и задачами.
"""

from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from .migrations import run_migrations
from .passwords import hash_password, verify_password

# Роли пользователя (иерархия аддитивна: admin ⊃ teacher ⊃ student).
ROLES = ("student", "teacher", "admin")


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    parent_name: str  # значение поля pra_subject

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_name": self.parent_name,
        }


@dataclass(frozen=True)
class Partition:
    id: int
    subject_id: int
    name: str
    constracted: int          # 0=одиночный, 1=конструктор, 2=группа, 3=тест
    generation_params: dict   # распарсенный JSON или {}

    def to_dict(self) -> dict:
        # generation_params целенаправленно не отдаём в публичный API —
        # это «кишки» (конфиг физического конструктора, список task_id
        # группы и т.п.). Если он понадобится конкретному веб-эндпоинту,
        # пусть достаёт его отдельно через get_partition().
        return {
            "id": self.id,
            "subject_id": self.subject_id,
            "name": self.name,
            "constracted": self.constracted,
        }


# Какой view_kind использовать для каждого constracted:
#   0 — single  (одиночное задание, кнопка «Сгенерировать»)
#   1 — table   (конструктор физики — таблица накопленных заданий)
#   2 — table   (группа — таблица заданий из разных детей)
#   3 — test    (тест с вариантами)
_VIEW_KIND_BY_CONSTRACTED = {
    0: "single",
    1: "table",
    2: "table",
    3: "test",
}


@dataclass(frozen=True)
class UserProfile:
    login: str
    fio: str
    group: str
    email: str
    about: str
    avatar_color: str
    created_at: float
    id: int = 0
    role: str = "student"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "login": self.login,
            "role": self.role,
            "fio": self.fio,
            "group": self.group,
            "email": self.email,
            "about": self.about,
            "avatar_color": self.avatar_color,
            "created_at": self.created_at,
        }


class Repository:
    """Доступ к таблицам Subjects, Partitions, users."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Создаёт файл БД и все таблицы, если они отсутствуют.
        Если файл повреждён — удаляет его и пересоздаёт."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute("PRAGMA integrity_check")
            except sqlite3.DatabaseError:
                import logging
                logging.getLogger(__name__).warning(
                    "Database %s is malformed, recreating…", self.db_path
                )
                self.db_path.unlink()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS Subjects (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_name  TEXT    NOT NULL DEFAULT '',
                    pra_subject   TEXT    NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS Partitions (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id           INTEGER NOT NULL DEFAULT 0,
                    partition_name       TEXT    NOT NULL DEFAULT '',
                    constracted          INTEGER NOT NULL DEFAULT 0,
                    generation_parametrs TEXT    NOT NULL DEFAULT ''
                );
            """)
            conn.commit()
            # Версионированные миграции: RBAC, владение, sync-колонки, таблицы
            # контура. Идемпотентно — на уже мигрированной БД это no-op.
            run_migrations(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    # ---------- Subjects ----------

    def list_subjects(self) -> List[Subject]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects"
            ).fetchall()
        return [Subject(r[0], r[1], r[2]) for r in rows]

    def get_subject_by_name(self, name: str) -> Optional[Subject]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects "
                "WHERE subject_name = ?",
                (name,),
            ).fetchone()
        return Subject(*row) if row else None

    # ---------- Partitions ----------

    def list_partitions_for_subject(self, subject_id: int) -> List[Partition]:
        # Tombstones (deleted_at) скрыты: для приложения удалённый раздел
        # не существует, строка живёт только ради offline-sync.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE subject_id = ? AND deleted_at IS NULL "
                "ORDER BY id",
                (subject_id,),
            ).fetchall()
        return [self._row_to_partition(r) for r in rows]

    def get_partition(self, partition_id: int) -> Optional[Partition]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE id = ? AND deleted_at IS NULL",
                (partition_id,),
            ).fetchone()
        return self._row_to_partition(row) if row else None

    def view_kind_for(self, partition: Partition) -> str:
        """Какое представление подобрать разделу."""
        return _VIEW_KIND_BY_CONSTRACTED.get(partition.constracted, "single")

    @staticmethod
    def _row_to_partition(row) -> Partition:
        params: dict = {}
        raw = row[4]
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    params = {"data": parsed}
            except json.JSONDecodeError:
                params = {"raw": raw}
        return Partition(
            id=row[0],
            subject_id=row[1],
            name=row[2],
            constracted=row[3],
            generation_params=params,
        )

    # ---------- Запись разделов ----------

    @staticmethod
    def _next_row_version(conn: sqlite3.Connection, table: str) -> int:
        """
        Следующий row_version — глобально монотонный per-таблица (НЕ по-строчный
        +1): курсор sync = «максимальный полученный row_version на тип сущности»
        (offline_sync_protocol.md §4), поэтому версии обязаны быть уникальны в
        пределах таблицы. SQLite сериализует писателей — гонки MAX+1 нет;
        на Postgres это станет sequence.
        """
        row = conn.execute(
            f"SELECT COALESCE(MAX(row_version), 0) + 1 FROM {table}"
        ).fetchone()
        return int(row[0])

    def ensure_subject(
        self, subject_id: int, name: str, parent_name: str | None = None
    ) -> int:
        """
        Гарантировать наличие предмета. Если subject_id уже занят, просто
        возвращаем его. Если в БД есть запись с таким же name — используем её id.
        Иначе — вставляем новую с подобранным id (или указанным, если свободен).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM Subjects WHERE id = ?", (subject_id,)
            ).fetchone()
            if row:
                return row[0]
            row = conn.execute(
                "SELECT id FROM Subjects WHERE subject_name = ?", (name,)
            ).fetchone()
            if row:
                return row[0]
            parent = parent_name if parent_name is not None else name
            ver = self._next_row_version(conn, "Subjects")
            now = time.time()
            try:
                conn.execute(
                    "INSERT INTO Subjects (id, subject_name, pra_subject, "
                    " row_version, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (subject_id, name, parent, ver, now),
                )
                conn.commit()
                return subject_id
            except sqlite3.IntegrityError:
                cur = conn.execute(
                    "INSERT INTO Subjects (subject_name, pra_subject, "
                    " row_version, updated_at) VALUES (?, ?, ?, ?)",
                    (name, parent, ver, now),
                )
                conn.commit()
                return cur.lastrowid

    def ensure_code_partition(
        self,
        partition_id: int,
        subject_id: int,
        name: str,
    ) -> None:
        """
        Гарантировать наличие записи раздела для code-only генератора
        (constracted=0, без generation_params).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, partition_name, subject_id, constracted "
                "FROM Partitions WHERE id = ?", (partition_id,)
            ).fetchone()
            if row is None:
                try:
                    conn.execute(
                        "INSERT INTO Partitions "
                        "(id, subject_id, partition_name, constracted, "
                        " generation_parametrs, row_version, updated_at) "
                        "VALUES (?, ?, ?, 0, '', ?, ?)",
                        (partition_id, subject_id, name,
                         self._next_row_version(conn, "Partitions"), time.time()),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
                return
            if row[3] == 0 and (row[1] != name or row[2] != subject_id):
                conn.execute(
                    "UPDATE Partitions SET partition_name = ?, subject_id = ?, "
                    "row_version = ?, updated_at = ? WHERE id = ?",
                    (name, subject_id,
                     self._next_row_version(conn, "Partitions"), time.time(),
                     partition_id),
                )
                conn.commit()

    def upsert_partition(
        self,
        subject_id: int,
        name: str,
        constracted: int,
        generation_params: dict | list | str,
    ) -> int:
        if isinstance(generation_params, (dict, list)):
            raw = json.dumps(generation_params, ensure_ascii=False)
        else:
            raw = str(generation_params)

        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id FROM Partitions WHERE subject_id = ? AND partition_name = ?",
                (subject_id, name),
            )
            existing = cur.fetchone()
            now = time.time()
            ver = self._next_row_version(conn, "Partitions")
            if existing:
                pid = existing[0]
                # Новый row_version + updated_at — основа offline-sync;
                # deleted_at сбрасывается: пересоздание раздела под старым
                # именем воскрешает tombstone-строку.
                conn.execute(
                    "UPDATE Partitions SET constracted = ?, generation_parametrs = ?, "
                    "row_version = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
                    (constracted, raw, ver, now, pid),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO Partitions "
                    "(subject_id, partition_name, constracted, generation_parametrs, "
                    " row_version, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (subject_id, name, constracted, raw, ver, now),
                )
                pid = cur.lastrowid
            conn.commit()
        return pid

    def delete_partition(self, partition_id: int) -> None:
        """Tombstone, не физическое удаление: офлайн-клиент узнаёт об
        удалении только по строке с deleted_at и новым row_version
        (offline_sync_protocol.md §2)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE Partitions SET deleted_at = ?, updated_at = ?, "
                "row_version = ? WHERE id = ? AND deleted_at IS NULL",
                (time.time(), time.time(),
                 self._next_row_version(conn, "Partitions"), partition_id),
            )
            conn.commit()

    # ---------- Карта constracted → kind редактора ----------

    EDITOR_KIND_BY_CONSTRACTED = {
        1: "fisic",
        2: "group",
        3: "test",
    }

    def editor_kind_for(self, partition: Partition) -> str | None:
        return self.EDITOR_KIND_BY_CONSTRACTED.get(partition.constracted)

    # ---------- Users (авторизация и профиль) ----------

    def ensure_users_table(self) -> None:
        """Создаёт таблицу users если её нет, добавляет новые колонки профиля
        в существующую (ALTER TABLE IF NOT EXISTS эмулируется через try/except)."""
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "  login TEXT PRIMARY KEY,"
                "  password TEXT NOT NULL DEFAULT '',"
                "  FIO TEXT NOT NULL DEFAULT '',"
                "  \"group\" TEXT NOT NULL DEFAULT '',"
                "  email TEXT NOT NULL DEFAULT '',"
                "  about TEXT NOT NULL DEFAULT '',"
                "  avatar_color TEXT NOT NULL DEFAULT '',"
                "  created_at REAL NOT NULL DEFAULT 0"
                ")"
            )
            for col, typedef in [
                ("email",        "TEXT NOT NULL DEFAULT ''"),
                ("about",        "TEXT NOT NULL DEFAULT ''"),
                ("avatar_color", "TEXT NOT NULL DEFAULT ''"),
                ("created_at",   "REAL NOT NULL DEFAULT 0"),
            ]:
                try:
                    conn.execute(f'ALTER TABLE users ADD COLUMN {col} {typedef}')
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    _USER_COLS = (
        "id, login, role, FIO, \"group\", email, about, avatar_color, created_at"
    )

    @staticmethod
    def _row_to_profile(row) -> UserProfile:
        return UserProfile(
            id=row[0] or 0, login=row[1], role=row[2] or "student",
            fio=row[3] or "", group=row[4] or "", email=row[5] or "",
            about=row[6] or "", avatar_color=row[7] or "", created_at=row[8] or 0.0,
        )

    def find_user(self, login: str, password: str) -> Optional[UserProfile]:
        """Проверяет логин/пароль. Понимает pbkdf2, а также унаследованные
        форматы (plaintext, sha256(login:password)) — при успешном входе на
        устаревшем формате пароль перехешируется в pbkdf2 (self._upgrade_password)."""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._USER_COLS}, password_hash FROM users WHERE login = ?",
                (login,),
            ).fetchone()
        if row is None:
            return None
        ok, needs_upgrade = verify_password(row[9] or "", password, login)
        if not ok:
            return None
        if needs_upgrade:
            self._upgrade_password(login, password)
        return self._row_to_profile(row)

    def _upgrade_password(self, login: str, password: str) -> None:
        """Перехешировать пароль в pbkdf2 и стереть плейнтекст из колонки password."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, password = '' WHERE login = ?",
                (hash_password(password), login),
            )
            conn.commit()

    def get_user_profile(self, login: str) -> Optional[UserProfile]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE login = ?",
                (login,),
            ).fetchone()
        return self._row_to_profile(row) if row else None

    def list_users(self) -> List[UserProfile]:
        """Все пользователи (админ-вьюха: список/смена роли). Без пароля."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._USER_COLS} FROM users ORDER BY login"
            ).fetchall()
        return [self._row_to_profile(r) for r in rows]

    def get_user_id(self, login: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE login = ?", (login,)
            ).fetchone()
        return row[0] if row else None

    def set_user_role(self, login: str, role: str) -> bool:
        """Назначить роль (админская операция). Возвращает True если найден."""
        if role not in ROLES:
            raise ValueError(f"Неизвестная роль {role!r}; допустимы {ROLES}.")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET role = ? WHERE login = ?", (role, login)
            )
            conn.commit()
            return cur.rowcount > 0

    def create_user(
        self, login: str, password: str, fio: str, group: str,
        email: str = "", role: str = "student",
    ) -> bool:
        """Регистрирует нового пользователя. Возвращает True при успехе,
        False если логин уже занят."""
        if role not in ROLES:
            raise ValueError(f"Неизвестная роль {role!r}; допустимы {ROLES}.")
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users "
                    "(login, password, password_hash, role, FIO, \"group\", "
                    " email, avatar_color, created_at) "
                    "VALUES (?, '', ?, ?, ?, ?, ?, '', ?)",
                    (login, hash_password(password), role, fio, group,
                     email, time.time()),
                )
                conn.execute(
                    "UPDATE users SET id = rowid WHERE rowid = ? AND id IS NULL",
                    (cur.lastrowid,),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_user_profile(
        self,
        login: str,
        fio: str,
        group: str,
        email: str,
        about: str,
        avatar_color: str,
    ) -> bool:
        """Обновляет поля профиля. Возвращает True если пользователь найден."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET FIO = ?, \"group\" = ?, email = ?, "
                "about = ?, avatar_color = ? WHERE login = ?",
                (fio, group, email, about, avatar_color, login),
            )
            conn.commit()
            return cur.rowcount > 0

    def change_user_password(
        self, login: str, current_password: str, new_password: str
    ) -> bool:
        """Меняет пароль. Проверяет текущий пароль (оба формата) перед сменой.
        Возвращает True при успехе, False при неверном текущем пароле."""
        profile = self.find_user(login, current_password)
        if profile is None:
            return False
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, password = '' WHERE login = ?",
                (hash_password(new_password), login),
            )
            conn.commit()
        return True

    # ---------- Владение контентом и видимость (RBAC) ----------
    #
    # Право enforcement'а по договору живёт в web_layer (см.
    # docs/architecture/rbac_and_data_model.md). Эти методы — детерминированные
    # предикаты над схемой, которыми web_layer и будущий contour_service
    # пользуются; сам сервис ролей не «решает», он их вычисляет.

    def subject_owner(self, subject_id: int) -> Optional[str]:
        """owner_user_id предмета (логин-строка); None — системный/встроенный."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT owner_user_id FROM Subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        return row[0] if row else None

    def create_subject(
        self, name: str, parent_name: str, owner_user_id: Optional[str] = None
    ) -> int:
        """Создать предмет с владельцем-логином (None = системный). id."""
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO Subjects "
                "(subject_name, pra_subject, owner_user_id, row_version, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, parent_name, owner_user_id,
                 self._next_row_version(conn, "Subjects"), now),
            )
            conn.commit()
            return cur.lastrowid

    def visible_subject_ids(self, user_id: Optional[str], role: str) -> List[int]:
        """
        Какие предметы видит пользователь: admin — все; остальные — системные
        (owner IS NULL) плюс свои. Удалённые (deleted_at) исключены.
        """
        with self._connect() as conn:
            if role == "admin":
                rows = conn.execute(
                    "SELECT id FROM Subjects WHERE deleted_at IS NULL ORDER BY id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM Subjects "
                    "WHERE deleted_at IS NULL "
                    "  AND (owner_user_id IS NULL OR owner_user_id = ?) "
                    "ORDER BY id",
                    (user_id,),
                ).fetchall()
        return [r[0] for r in rows]

    def can_edit_subject(self, user_id: Optional[str], role: str, subject_id: int) -> bool:
        """
        Кто может редактировать предмет: admin — всегда; teacher — только свои;
        системные предметы (owner IS NULL) — только admin; student — никогда.
        """
        if role == "admin":
            return True
        if role != "teacher":
            return False
        owner = self.subject_owner(subject_id)
        return owner is not None and owner == user_id

    # ---------- Группы и назначения ----------

    def create_group(self, name: str, created_by: Optional[int] = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO groups (name, created_by, created_at) VALUES (?, ?, ?)",
                (name, created_by, time.time()),
            )
            conn.commit()
            return cur.lastrowid

    def add_group_member(self, group_id: int, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO group_members (group_id, user_id) "
                "VALUES (?, ?)",
                (group_id, user_id),
            )
            conn.commit()

    def list_group_members(self, group_id: int) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id FROM group_members WHERE group_id = ? "
                "ORDER BY user_id",
                (group_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def assign_teacher_to_group(self, teacher_id: int, group_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO teacher_groups (teacher_id, group_id) "
                "VALUES (?, ?)",
                (teacher_id, group_id),
            )
            conn.commit()

    def teacher_group_ids(self, teacher_id: int) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id FROM teacher_groups WHERE teacher_id = ? "
                "ORDER BY group_id",
                (teacher_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def user_group_ids(self, user_id: int) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id FROM group_members WHERE user_id = ? "
                "ORDER BY group_id",
                (user_id,),
            ).fetchall()
        return [r[0] for r in rows]

    # ---------- WordStats ----------

    def ensure_word_stats_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS WordStats ("
                "  user_id TEXT NOT NULL,"
                "  term TEXT NOT NULL,"
                "  times_shown INTEGER NOT NULL DEFAULT 0,"
                "  times_correct INTEGER NOT NULL DEFAULT 0,"
                "  times_wrong INTEGER NOT NULL DEFAULT 0,"
                "  last_seen REAL NOT NULL DEFAULT 0,"
                "  PRIMARY KEY (user_id, term)"
                ")"
            )
            conn.commit()

    def fetch_word_stats(self, user_id: str, terms: List[str]) -> dict:
        from .word_stats import WordStat

        if not terms:
            return {}
        out: dict[str, WordStat] = {}
        chunk_size = 500
        with self._connect() as conn:
            for i in range(0, len(terms), chunk_size):
                chunk = terms[i:i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT term, times_shown, times_correct, times_wrong, "
                    f"       last_seen "
                    f"FROM WordStats "
                    f"WHERE user_id = ? AND term IN ({placeholders})",
                    (user_id, *chunk),
                ).fetchall()
                for r in rows:
                    out[r[0]] = WordStat(
                        term=r[0],
                        times_shown=r[1],
                        times_correct=r[2],
                        times_wrong=r[3],
                        last_seen=r[4],
                    )
        return out

    def upsert_word_stat(
        self, user_id: str, term: str, correct: bool, now: float
    ) -> None:
        delta_correct = 1 if correct else 0
        delta_wrong = 0 if correct else 1
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO WordStats "
                "(user_id, term, times_shown, times_correct, times_wrong, last_seen) "
                "VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(user_id, term) DO UPDATE SET "
                "  times_shown = times_shown + 1, "
                "  times_correct = times_correct + ?, "
                "  times_wrong = times_wrong + ?, "
                "  last_seen = ?",
                (user_id, term, delta_correct, delta_wrong, now,
                 delta_correct, delta_wrong, now),
            )
            conn.commit()

    def fetch_all_word_stats(self, user_id: str) -> list:
        from .word_stats import WordStat

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT term, times_shown, times_correct, times_wrong, last_seen "
                "FROM WordStats WHERE user_id = ? "
                "ORDER BY last_seen DESC",
                (user_id,),
            ).fetchall()
        return [
            WordStat(
                term=r[0],
                times_shown=r[1],
                times_correct=r[2],
                times_wrong=r[3],
                last_seen=r[4],
            )
            for r in rows
        ]
