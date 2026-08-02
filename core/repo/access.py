"""
Разграничение доступа: выдачи предметов преподавателям и клиенты
публичного API.

Два субъекта, одна механика: преподавателю выдают предмет и
приложению выдают предмет. Держим рядом намеренно — расходиться им
нельзя, иначе витрина и публичный каталог начнут отвечать по-разному.
"""

from __future__ import annotations
import time
import uuid
from typing import List, Optional


class AccessMixin:
    """Выдачи предметов, ключи приложений, квоты, публичные id."""
    # ---------- Выдачи предметов преподавателям ----------
    #
    # Модель — docs/subject_grants.md (репозиторий Generator). Админ раздаёт
    # преподавателям доступ к предметам; ключ выдачи — логин. Здесь только
    # чтение/запись: кто вправе раздавать и что считается корректным набором,
    # решает core/grants_api.py (та же граница, что у assignments).
    #
    # scope_version («эпоха скоупа») инкрементируется при ЛЮБОМ изменении
    # видимого пользователю набора — выдача, отзыв, смена режима умолчания,
    # смена роли. Курсорный pull изменение прав не переносит, поэтому эпоха и
    # есть то событие, по которому клиент пересобирает свой набор.

    DEFAULT_ACCESS_VALUES = ("all", "none")
    _DEFAULT_ACCESS_KEY = "default_subject_access"

    # --- Общие серверные настройки (app_settings) ---

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def default_subject_access(self) -> str:
        """'all' — преподаватель без выдач видит все предметы; 'none' — только
        выданные. Неизвестное значение трактуем как 'all': умолчание
        намеренно разрешающее, кривая настройка не должна запирать витрину."""
        value = self.get_setting(self._DEFAULT_ACCESS_KEY, "all")
        return value if value in self.DEFAULT_ACCESS_VALUES else "all"

    def set_default_subject_access(self, value: str) -> None:
        """Переключить режим умолчания. Атомарно с инкрементом эпохи ВСЕМ
        преподавателям: переключение меняет видимый набор у каждого, у кого
        нет явных выдач, и без инкремента это изменение до клиентов не
        доедет."""
        if value not in self.DEFAULT_ACCESS_VALUES:
            raise ValueError(
                f"default_subject_access: 'all'|'none', не {value!r}")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (self._DEFAULT_ACCESS_KEY, value),
            )
            conn.execute(
                "UPDATE users SET scope_version = scope_version + 1 "
                "WHERE role = 'teacher'"
            )

    # --- Эпоха скоупа ---

    def scope_version(self, login: Optional[str]) -> int:
        """Текущая эпоха пользователя; 0 — пользователь неизвестен (гость)."""
        if not login:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scope_version FROM users WHERE login = ?", (login,)
            ).fetchone()
        return int(row[0] or 0) if row else 0

    def bump_scope_version(self, login: str) -> int:
        """Инкремент эпохи одного пользователя. Возвращает новое значение
        (0 — пользователя нет)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET scope_version = scope_version + 1 "
                "WHERE login = ?",
                (login,),
            )
            row = conn.execute(
                "SELECT scope_version FROM users WHERE login = ?", (login,)
            ).fetchone()
        return int(row[0] or 0) if row else 0

    # --- Сами выдачи ---

    def subject_grants(self, teacher_login: str) -> List[int]:
        """Явно выданные преподавателю subject_id (удалённые предметы
        отфильтрованы — выдача на tombstone смысла не имеет)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT g.subject_id FROM subject_grants g "
                "JOIN Subjects s ON s.id = g.subject_id "
                "WHERE g.teacher_login = ? AND s.deleted_at IS NULL "
                "ORDER BY g.subject_id",
                (teacher_login,),
            ).fetchall()
        return [r[0] for r in rows]

    def all_subject_grants(self) -> dict[str, List[int]]:
        """Вся матрица разом: {логин: [subject_id]} — данные админской
        вкладки одним запросом вместо N запросов по преподавателям."""
        out: dict[str, List[int]] = {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT g.teacher_login, g.subject_id FROM subject_grants g "
                "JOIN Subjects s ON s.id = g.subject_id "
                "WHERE s.deleted_at IS NULL "
                "ORDER BY g.teacher_login, g.subject_id"
            ).fetchall()
        for login, subject_id in rows:
            out.setdefault(login, []).append(subject_id)
        return out

    def replace_subject_grants(
        self, teacher_login: str, subject_ids, granted_by: str = "",
    ) -> int:
        """
        Заменить набор выдач преподавателя ЦЕЛИКОМ (не дельта) и вернуть его
        новую эпоху.

        Полная замена, потому что матрица правится строкой: повторное
        применение того же набора ничего не меняет, а отзыв не требует
        отдельной операции. Всё одной транзакцией — иначе клиент, попавший
        между DELETE и INSERT, увидел бы пустой набор и подчистил бы у себя
        живой контент.

        Эпоха инкрементируется ВСЕГДА, даже если набор не изменился: сверять
        старое с новым ради экономии одного resync'а — цена сложности выше
        выгоды, а лишняя пересборка идемпотентна.
        """
        ids = sorted({int(s) for s in subject_ids})
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM subject_grants WHERE teacher_login = ?",
                         (teacher_login,))
            conn.executemany(
                "INSERT INTO subject_grants "
                "(teacher_login, subject_id, granted_by, granted_at) "
                "VALUES (?, ?, ?, ?)",
                [(teacher_login, sid, granted_by, now) for sid in ids],
            )
            conn.execute(
                "UPDATE users SET scope_version = scope_version + 1 "
                "WHERE login = ?",
                (teacher_login,),
            )
            row = conn.execute(
                "SELECT scope_version FROM users WHERE login = ?",
                (teacher_login,),
            ).fetchone()
        return int(row[0] or 0) if row else 0

    # ---------- Публичный API: клиенты, ключи, квоты, публичные id ----------
    #
    # Субъект здесь — приложение, а не человек (см. public_api.md). Repository
    # хранит и считает; что считать корректным ключом и когда отказать по
    # квоте, решает core/api_clients.py.

    _CLIENT_COLS = ("id, name, owner_login, status, daily_quota, created_at")

    @staticmethod
    def _row_to_client(row) -> dict:
        return {"id": row[0], "name": row[1], "owner_login": row[2],
                "status": row[3], "daily_quota": int(row[4] or 0),
                "created_at": row[5] or 0.0}

    def create_api_client(self, name: str, owner_login: Optional[str],
                          daily_quota: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO api_clients "
                "(name, owner_login, status, daily_quota, created_at) "
                "VALUES (?, ?, 'active', ?, ?)",
                (name, owner_login, int(daily_quota), time.time()),
            )
            return cur.lastrowid

    def get_api_client(self, client_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._CLIENT_COLS} FROM api_clients WHERE id = ?",
                (client_id,),
            ).fetchone()
        return self._row_to_client(row) if row else None

    def list_api_clients(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._CLIENT_COLS} FROM api_clients ORDER BY id"
            ).fetchall()
        return [self._row_to_client(r) for r in rows]

    def set_api_client_status(self, client_id: int, status: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_clients SET status = ? WHERE id = ?",
                (status, client_id),
            )
            return cur.rowcount > 0

    def set_api_client_quota(self, client_id: int, daily_quota: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_clients SET daily_quota = ? WHERE id = ?",
                (int(daily_quota), client_id),
            )
            return cur.rowcount > 0

    def add_api_key(self, key_hash: str, client_id: int, kind: str,
                    prefix: str, allowed_origins: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, client_id, kind, prefix, "
                " allowed_origins, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key_hash, client_id, kind, prefix, allowed_origins,
                 time.time()),
            )

    def find_api_key(self, key_hash: str) -> Optional[dict]:
        """Ключ вместе с его клиентом — одним запросом: это горячий путь,
        через него проходит каждый вызов публичного API."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT k.key_hash, k.client_id, k.kind, k.prefix, "
                "       k.allowed_origins, k.revoked_at, "
                "       c.name, c.status, c.daily_quota "
                "FROM api_keys k JOIN api_clients c ON c.id = k.client_id "
                "WHERE k.key_hash = ?",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        return {"key_hash": row[0], "client_id": row[1], "kind": row[2],
                "prefix": row[3], "allowed_origins": row[4],
                "revoked_at": row[5], "client_name": row[6],
                "client_status": row[7], "daily_quota": int(row[8] or 0)}

    def list_api_keys(self, client_id: int) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prefix, kind, allowed_origins, created_at, revoked_at "
                "FROM api_keys WHERE client_id = ? ORDER BY created_at",
                (client_id,),
            ).fetchall()
        return [{"prefix": r[0], "kind": r[1], "allowed_origins": r[2],
                 "created_at": r[3], "revoked_at": r[4]} for r in rows]

    def revoke_api_key(self, client_id: int, prefix: str) -> bool:
        """Отзыв по префиксу: полного ключа нет ни у кого, включая владельца
        — он и виден в списке только префиксом."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET revoked_at = ? "
                "WHERE client_id = ? AND prefix = ? AND revoked_at IS NULL",
                (time.time(), client_id, prefix),
            )
            return cur.rowcount > 0

    def api_client_subject_ids(self, client_id: int) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.id FROM api_client_subjects a "
                "JOIN Subjects s ON s.id = a.subject_id "
                "WHERE a.client_id = ? AND s.deleted_at IS NULL "
                "ORDER BY s.id",
                (client_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def replace_api_client_subjects(self, client_id: int, subject_ids) -> None:
        ids = sorted({int(s) for s in subject_ids})
        with self._connect() as conn:
            conn.execute("DELETE FROM api_client_subjects WHERE client_id = ?",
                         (client_id,))
            conn.executemany(
                "INSERT INTO api_client_subjects (client_id, subject_id) "
                "VALUES (?, ?)",
                [(client_id, sid) for sid in ids],
            )

    def builtin_subject_ids(self) -> List[int]:
        """Встроенные предметы (owner IS NULL) — они принадлежат продукту, а
        не преподавателям, и только их публичный API отдаёт по умолчанию."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM Subjects "
                "WHERE owner_user_id IS NULL AND deleted_at IS NULL ORDER BY id"
            ).fetchall()
        return [r[0] for r in rows]

    # --- Учёт вызовов ---

    def bump_api_usage(self, client_id: int, day: str) -> int:
        """Увеличить счётчик вызовов и вернуть новое значение (атомарно)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_usage (client_id, day, calls) VALUES (?, ?, 1) "
                "ON CONFLICT(client_id, day) DO UPDATE SET calls = calls + 1",
                (client_id, day),
            )
            return int(conn.execute(
                "SELECT calls FROM api_usage WHERE client_id = ? AND day = ?",
                (client_id, day),
            ).fetchone()[0])

    def api_usage(self, client_id: int, day: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT calls FROM api_usage WHERE client_id = ? AND day = ?",
                (client_id, day),
            ).fetchone()
        return int(row[0]) if row else 0

    # --- Публичные идентификаторы ---

    _PUBLIC_ID_TABLES = {"subject": "Subjects", "partition": "Partitions"}

    def public_id(self, kind: str, row_id: int) -> Optional[str]:
        """
        Стабильный внешний id строки; создаётся при первом обращении.

        Ленивая генерация, а не колонка со значением по умолчанию на каждом
        пути вставки: строки заводят и bootstrap, и sync, и CRUD разделов, и
        ради поля, нужного одному потребителю, править их все — лишний риск.
        Миграция 008 проставила id существующим строкам, здесь дозаполняются
        появившиеся позже.
        """
        table = self._PUBLIC_ID_TABLES.get(kind)
        if table is None:
            raise ValueError(f"Неизвестный вид сущности {kind!r}.")
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT public_id FROM {table} WHERE id = ?", (row_id,)
            ).fetchone()
            if row is None:
                return None
            if row[0]:
                return row[0]
            new_id = str(uuid.uuid4())
            conn.execute(f"UPDATE {table} SET public_id = ? WHERE id = ?",
                         (new_id, row_id))
            return new_id

    def resolve_public_id(self, kind: str, public_id: str) -> Optional[int]:
        table = self._PUBLIC_ID_TABLES.get(kind)
        if table is None:
            raise ValueError(f"Неизвестный вид сущности {kind!r}.")
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT id FROM {table} "
                f"WHERE public_id = ? AND deleted_at IS NULL",
                (public_id,),
            ).fetchone()
        return row[0] if row else None
