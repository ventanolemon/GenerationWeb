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

    def to_dict(self) -> dict:
        return {
            "login": self.login,
            "fio": self.fio,
            "group": self.group,
            "email": self.email,
            "about": self.about,
            "avatar_color": self.avatar_color,
            "created_at": self.created_at,
        }


def _hash_password(login: str, password: str) -> str:
    """sha256(login:password) — используется для новых регистраций через веб.
    Существующие десктопные аккаунты хранят пароль в открытом виде — find_user
    проверяет оба формата, чтобы не сломать обратную совместимость."""
    return hashlib.sha256(f"{login}:{password}".encode()).hexdigest()


class Repository:
    """Доступ к таблицам Subjects, Partitions, users."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE subject_id = ? ORDER BY id",
                (subject_id,),
            ).fetchall()
        return [self._row_to_partition(r) for r in rows]

    def get_partition(self, partition_id: int) -> Optional[Partition]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE id = ?",
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
            try:
                conn.execute(
                    "INSERT INTO Subjects (id, subject_name, pra_subject) "
                    "VALUES (?, ?, ?)",
                    (subject_id, name, parent),
                )
                conn.commit()
                return subject_id
            except sqlite3.IntegrityError:
                cur = conn.execute(
                    "INSERT INTO Subjects (subject_name, pra_subject) VALUES (?, ?)",
                    (name, parent),
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
                        " generation_parametrs) VALUES (?, ?, ?, 0, '')",
                        (partition_id, subject_id, name),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
                return
            if row[3] == 0 and (row[1] != name or row[2] != subject_id):
                conn.execute(
                    "UPDATE Partitions SET partition_name = ?, subject_id = ? "
                    "WHERE id = ?", (name, subject_id, partition_id)
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
            if existing:
                pid = existing[0]
                conn.execute(
                    "UPDATE Partitions SET constracted = ?, generation_parametrs = ? "
                    "WHERE id = ?",
                    (constracted, raw, pid),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO Partitions "
                    "(subject_id, partition_name, constracted, generation_parametrs) "
                    "VALUES (?, ?, ?, ?)",
                    (subject_id, name, constracted, raw),
                )
                pid = cur.lastrowid
            conn.commit()
        return pid

    def delete_partition(self, partition_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM Partitions WHERE id = ?", (partition_id,)
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

    def find_user(self, login: str, password: str) -> Optional[UserProfile]:
        """Проверяет логин/пароль. Принимает пароль в открытом виде (старые
        десктопные аккаунты) и в виде sha256-хеша (новые веб-регистрации)."""
        pw_hash = _hash_password(login, password)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT login, FIO, \"group\", email, about, avatar_color, created_at "
                "FROM users "
                "WHERE login = ? AND (password = ? OR password = ?)",
                (login, pw_hash, password),
            ).fetchone()
        if row is None:
            return None
        return UserProfile(
            login=row[0], fio=row[1] or "", group=row[2] or "",
            email=row[3] or "", about=row[4] or "",
            avatar_color=row[5] or "", created_at=row[6] or 0.0,
        )

    def get_user_profile(self, login: str) -> Optional[UserProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT login, FIO, \"group\", email, about, avatar_color, created_at "
                "FROM users WHERE login = ?",
                (login,),
            ).fetchone()
        if row is None:
            return None
        return UserProfile(
            login=row[0], fio=row[1] or "", group=row[2] or "",
            email=row[3] or "", about=row[4] or "",
            avatar_color=row[5] or "", created_at=row[6] or 0.0,
        )

    def create_user(
        self, login: str, password: str, fio: str, group: str, email: str = ""
    ) -> bool:
        """Регистрирует нового пользователя. Возвращает True при успехе,
        False если логин уже занят."""
        pw_hash = _hash_password(login, password)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users "
                    "(login, password, FIO, \"group\", email, avatar_color, created_at) "
                    "VALUES (?, ?, ?, ?, ?, '', ?)",
                    (login, pw_hash, fio, group, email, time.time()),
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
        new_hash = _hash_password(login, new_password)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password = ? WHERE login = ?",
                (new_hash, login),
            )
            conn.commit()
        return True

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
