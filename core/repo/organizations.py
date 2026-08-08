"""
Организации: контейнер для людей, групп и контента (§8 плана).

Слой доступа. Смысл и инварианты — в `core/organizations_api.py`; здесь
только строки, как и в остальных доменных миксинах.
"""

from __future__ import annotations

import time
from typing import List, Optional


class OrganizationsMixin:
    """Организации и принадлежность к ним."""

    _ORG_COLS = ("id, name, parent_id, owner_login, default_subject_access, "
                 "created_at")

    @staticmethod
    def _row_to_org(row) -> dict:
        return {"id": row[0], "name": row[1], "parent_id": row[2],
                "owner_login": row[3], "default_subject_access": row[4],
                "created_at": row[5]}

    # ---------- Чтение ----------

    def list_organizations(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._ORG_COLS} FROM organizations ORDER BY id"
            ).fetchall()
        return [self._row_to_org(r) for r in rows]

    def get_organization(self, org_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._ORG_COLS} FROM organizations WHERE id = ?",
                (int(org_id),),
            ).fetchone()
        return self._row_to_org(row) if row else None

    def default_organization_id(self) -> Optional[int]:
        """Организация «по умолчанию» — самая ранняя. В неё попадают новички."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else None

    def user_organization_id(self, login: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT organization_id FROM users WHERE login = ?", (login,)
            ).fetchone()
        return row[0] if row else None

    def organization_members(self, org_id: int) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT login FROM users WHERE organization_id = ? "
                "ORDER BY login", (int(org_id),)).fetchall()
        return [r[0] for r in rows]

    # ---------- Запись ----------

    def create_organization(self, name: str, *, parent_id: Optional[int] = None,
                            owner_login: Optional[str] = None,
                            default_subject_access: str = "all") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO organizations (name, parent_id, owner_login, "
                "default_subject_access, created_at) VALUES (?,?,?,?,?)",
                (name, parent_id, owner_login, default_subject_access,
                 time.time()),
            )
            return cur.lastrowid

    def rename_organization(self, org_id: int, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE organizations SET name = ? WHERE id = ?",
                               (name, int(org_id)))
            return cur.rowcount > 0

    def set_organization_owner(self, org_id: int,
                               owner_login: Optional[str]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE organizations SET owner_login = ? WHERE id = ?",
                (owner_login, int(org_id)))
            return cur.rowcount > 0

    def set_organization_default_access(self, org_id: int, value: str) -> bool:
        if value not in ("all", "none"):
            raise ValueError(f"default_subject_access: 'all'|'none', не {value!r}")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE organizations SET default_subject_access = ? "
                "WHERE id = ?", (value, int(org_id)))
            return cur.rowcount > 0

    def set_user_organization(self, login: str,
                              org_id: Optional[int]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET organization_id = ? WHERE login = ?",
                (org_id, login))
            return cur.rowcount > 0

    def set_subject_organization(self, subject_id: int,
                                 org_id: Optional[int]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE Subjects SET organization_id = ? WHERE id = ?",
                (org_id, int(subject_id)))
            return cur.rowcount > 0

    def group_organization_id(self, group_id: int) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT organization_id FROM groups WHERE id = ?",
                (int(group_id),)).fetchone()
        return row[0] if row else None

    def set_group_organization(self, group_id: int,
                               org_id: Optional[int]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE groups SET organization_id = ? WHERE id = ?",
                (org_id, int(group_id)))
            return cur.rowcount > 0

    def subject_organization_id(self, subject_id: int) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT organization_id FROM Subjects WHERE id = ?",
                (int(subject_id),)).fetchone()
        return row[0] if row else None

    def effective_default_access(self, login: Optional[str]) -> str:
        """
        Умолчание видимости, действующее для этого человека.

        Настройка переехала из `app_settings` (одна на развёртывание) в
        организацию: выдачи работают внутри организации, и умолчание для
        них обязано быть там же. Строка `app_settings` осталась значением
        для тех, кто вне организаций, и точкой отсчёта для новых.
        """
        org_id = self.user_organization_id(login or "")
        if org_id is not None:
            org = self.get_organization(org_id)
            if org:
                return org["default_subject_access"]
        return self.default_subject_access()

    # ---------- Администратор развёртывания ----------

    def is_superuser(self, login: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT is_superuser FROM users WHERE login = ?", (login,)
            ).fetchone()
        return bool(row and row[0])

    def list_superusers(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT login FROM users WHERE is_superuser = 1 ORDER BY login"
            ).fetchall()
        return [r[0] for r in rows]

    def set_superuser(self, login: str, value: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET is_superuser = ? WHERE login = ?",
                (1 if value else 0, login))
            return cur.rowcount > 0
