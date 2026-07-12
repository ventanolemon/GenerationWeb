"""
Тесты администрирования пользователей (core/admin_api) — headless, свежая
SQLite на каждый тест.

Запуск: python -m unittest core.test_admin_api  (из корня монорепо)
"""

from __future__ import annotations
import os
import tempfile
import unittest

from core import admin_api
from core.repository import Repository


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


class AdminApiTestBase(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        self.repo = Repository(self.db)

    def tearDown(self):
        os.unlink(self.db)


class ListUsersTests(AdminApiTestBase):
    def test_lists_all_users_without_password(self):
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "КСБО-11-24", role="teacher")
        users = admin_api.list_users(self.repo)
        logins = {u["login"] for u in users}
        self.assertEqual(logins, {"root", "alla"})
        self.assertTrue(all("password" not in u for u in users))
        by_login = {u["login"]: u for u in users}
        self.assertEqual(by_login["alla"]["role"], "teacher")
        self.assertEqual(by_login["alla"]["group"], "КСБО-11-24")


class ChangeRoleTests(AdminApiTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")

    def test_admin_promotes_teacher_to_admin(self):
        out = admin_api.change_role(self.repo, actor_login="root",
                                    target_login="alla", new_role="admin")
        self.assertEqual(out, {"login": "alla", "role": "admin"})
        self.assertEqual(self.repo.find_user("alla", "p").role, "admin")

    def test_rejects_self_change(self):
        with self.assertRaisesRegex(admin_api.AdminActionError, "собственную"):
            admin_api.change_role(self.repo, actor_login="root",
                                  target_login="root", new_role="teacher")

    def test_rejects_unknown_role(self):
        with self.assertRaisesRegex(admin_api.AdminActionError, "роль"):
            admin_api.change_role(self.repo, actor_login="root",
                                  target_login="alla", new_role="superadmin")

    def test_rejects_unknown_user(self):
        with self.assertRaisesRegex(admin_api.AdminActionError, "не найден"):
            admin_api.change_role(self.repo, actor_login="root",
                                  target_login="ghost", new_role="teacher")

    def test_rejects_demoting_last_admin(self):
        # root — единственный admin; alla пытается его понизить.
        with self.assertRaisesRegex(admin_api.AdminActionError, "последнего"):
            admin_api.change_role(self.repo, actor_login="alla",
                                  target_login="root", new_role="teacher")
        self.assertEqual(self.repo.find_user("root", "p").role, "admin")

    def test_allows_demoting_admin_when_another_admin_remains(self):
        self.repo.create_user("boris", "p", "Борис", "", role="admin")
        out = admin_api.change_role(self.repo, actor_login="alla",
                                    target_login="root", new_role="teacher")
        self.assertEqual(out["role"], "teacher")
        self.assertEqual(self.repo.find_user("root", "p").role, "teacher")
        self.assertEqual(self.repo.find_user("boris", "p").role, "admin")


class RouterTests(AdminApiTestBase):
    """Тонкий HTTP-адаптер: 401 без identity, 403 не-admin, 200 admin;
    доменные ошибки → 400."""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import admin as admin_router

        app = FastAPI()
        app.include_router(admin_router.router)
        app.state.repo = self.repo
        return TestClient(app)

    def setUp(self):
        super().setUp()
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")

    def test_401_without_identity(self):
        r = self._client().get("/admin/users")
        self.assertEqual(r.status_code, 401)

    def test_403_for_non_admin(self):
        r = self._client().get(
            "/admin/users",
            headers={"X-User-Id": "alla", "X-User-Role": "teacher"},
        )
        self.assertEqual(r.status_code, 403)

    def test_200_lists_users_for_admin(self):
        r = self._client().get(
            "/admin/users",
            headers={"X-User-Id": "root", "X-User-Role": "admin"},
        )
        self.assertEqual(r.status_code, 200)
        logins = {u["login"] for u in r.json()["users"]}
        self.assertEqual(logins, {"root", "alla"})

    def test_change_role_400_on_self_change(self):
        r = self._client().post(
            "/admin/users/root/role",
            json={"role": "teacher"},
            headers={"X-User-Id": "root", "X-User-Role": "admin"},
        )
        self.assertEqual(r.status_code, 400)

    def test_change_role_200_promotes_user(self):
        r = self._client().post(
            "/admin/users/alla/role",
            json={"role": "admin"},
            headers={"X-User-Id": "root", "X-User-Role": "admin"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"login": "alla", "role": "admin"})


if __name__ == "__main__":
    unittest.main()
