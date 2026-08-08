"""
Пользователи: аутентификация, профиль, роли.
"""

from __future__ import annotations
import sqlite3
import time
from typing import List, Optional

from ..passwords import hash_password, verify_password
from .models import ROLES, UserProfile


class UsersMixin:
    """Учётные записи и профили."""
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
            return cur.rowcount > 0

    def create_user(
        self, login: str, password: str, fio: str, group: str,
        email: str = "", role: str = "student",
        organization_id: Optional[int] = None,
    ) -> bool:
        """Регистрирует нового пользователя. Возвращает True при успехе,
        False если логин уже занят.

        Без явной организации новичок попадает в организацию по умолчанию —
        ту, что завела миграция 014. Иначе он не видел бы ничего и ждал
        приёма, а на развёртывании с самостоятельной регистрацией это
        означало бы, что зарегистрироваться можно, а пользоваться нельзя.
        Перевести его в другую организацию — отдельная админская операция."""
        if role not in ROLES:
            raise ValueError(f"Неизвестная роль {role!r}; допустимы {ROLES}.")
        with self._connect() as conn:
            if organization_id is None:
                row = conn.execute(
                    "SELECT id FROM organizations ORDER BY id LIMIT 1"
                ).fetchone()
                organization_id = row[0] if row else None
            try:
                cur = conn.execute(
                    "INSERT INTO users "
                    "(login, password, password_hash, role, FIO, \"group\", "
                    " email, avatar_color, created_at, organization_id) "
                    "VALUES (?, '', ?, ?, ?, ?, ?, '', ?, ?)",
                    (login, hash_password(password), role, fio, group,
                     email, time.time(), organization_id),
                )
                conn.execute(
                    "UPDATE users SET id = rowid WHERE rowid = ? AND id IS NULL",
                    (cur.lastrowid,),
                )
                # Метка курса из регистрации → структурная группа: создаём
                # группу по имени (если ещё нет) и зачисляем. Так свободный
                # users."group" и group_members остаются согласованными без
                # ручного администрирования (см. миграцию 003).
                label = (group or "").strip()
                if label:
                    grp = conn.execute(
                        "SELECT id FROM groups WHERE name = ?", (label,)
                    ).fetchone()
                    if grp:
                        gid = grp[0]
                    else:
                        gc = conn.execute(
                            "INSERT INTO groups (name, created_by, created_at) "
                            "VALUES (?, NULL, ?)",
                            (label, time.time()),
                        )
                        gid = gc.lastrowid
                    conn.execute(
                        "INSERT OR IGNORE INTO group_members (group_id, user_id) "
                        "VALUES (?, ?)",
                        (gid, login),
                    )
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
        return True

    # ---------- Сессии входа ----------
    # Хранение токенов; выдача и проверка — в core/auth_sessions.py. Здесь
    # только доступ к строкам, как и в остальных методах слоя.

    def add_auth_session(self, token_hash: str, login: str, *,
                         expires_at: float, user_agent: str = "") -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_sessions (token_hash, login, created_at, "
                "last_seen_at, expires_at, user_agent) VALUES (?,?,?,?,?,?)",
                (token_hash, login, now, now, float(expires_at),
                 user_agent[:200]),
            )

    def find_auth_session(self, token_hash: str) -> Optional[dict]:
        """
        Строка сессии вместе со СВЕЖЕЙ ролью из `users`.

        Роль, организация и флаг администратора развёртывания join'ятся, а
        не хранятся в сессии: они обязаны меняться в тот же миг, что и в
        БД. Хранили бы — понижение админа и перевод между организациями не
        действовали бы до истечения сессии.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.token_hash, s.login, s.created_at, s.last_seen_at, "
                "       s.expires_at, s.revoked_at, u.role, "
                "       u.organization_id, u.is_superuser "
                "FROM auth_sessions s JOIN users u ON u.login = s.login "
                "WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return {"token_hash": row[0], "login": row[1], "created_at": row[2],
                "last_seen_at": row[3], "expires_at": row[4],
                "revoked_at": row[5], "role": row[6],
                "organization_id": row[7], "is_superuser": bool(row[8])}

    def touch_auth_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (time.time(), token_hash),
            )

    def revoke_auth_session(self, token_hash: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (time.time(), token_hash),
            )
            return cur.rowcount > 0

    def revoke_auth_sessions_for(self, login: str) -> int:
        """Погасить все сессии пользователя — смена пароля, увольнение,
        разбор инцидента. Возвращает, сколько погасило."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? "
                "WHERE login = ? AND revoked_at IS NULL",
                (time.time(), login),
            )
            return cur.rowcount

    def purge_expired_auth_sessions(self, *, keep_seconds: float = 0.0) -> int:
        """Выбросить давно просроченные строки. Отозванные держим `keep_seconds`
        после истечения — по ним разбирают инциденты."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at < ?",
                (time.time() - float(keep_seconds),),
            )
            return cur.rowcount

    def list_auth_sessions(self, login: str) -> List[dict]:
        """Живые сессии пользователя — для экрана «где я вошёл»."""
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT token_hash, created_at, last_seen_at, expires_at, "
                "       user_agent FROM auth_sessions "
                "WHERE login = ? AND revoked_at IS NULL AND expires_at > ? "
                "ORDER BY last_seen_at DESC",
                (login, now),
            ).fetchall()
        return [{"token_hash": r[0], "created_at": r[1], "last_seen_at": r[2],
                 "expires_at": r[3], "user_agent": r[4]} for r in rows]
