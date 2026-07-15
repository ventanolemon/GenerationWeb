"""
Тесты групп: seed из users."group", авто-зачисление при регистрации,
admin-CRUD с guardrail'ами, teacher read-view, HTTP-роутер.

Запуск: python -m unittest core.test_groups_api  (из корня монорепо)
"""

from __future__ import annotations
import os
import tempfile
import unittest

from core import groups_api
from core.repository import Repository


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


class GroupsTestBase(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        self.repo = Repository(self.db)

    def tearDown(self):
        os.unlink(self.db)


class AutoEnrollTests(GroupsTestBase):
    def test_create_user_with_label_enrolls_into_structural_group(self):
        self.repo.create_user("s1", "p", "Иванов", "КСБО-11-24")
        self.repo.create_user("s2", "p", "Петров", "КСБО-11-24")
        grp = self.repo.group_by_name("КСБО-11-24")
        self.assertIsNotNone(grp)
        self.assertEqual(self.repo.list_group_members(grp.id), ["s1", "s2"])

    def test_create_user_without_label_creates_no_group(self):
        self.repo.create_user("teach", "p", "Препод", "", role="teacher")
        self.assertEqual(self.repo.list_groups(), [])

    def test_second_label_reuses_same_group(self):
        self.repo.create_user("s1", "p", "С1", "Г1")
        self.repo.create_user("s2", "p", "С2", "Г1")
        groups = self.repo.list_groups()
        self.assertEqual(len(groups), 1)


class SeedMigrationTests(unittest.TestCase):
    """Миграция 003 засеивает структурные группы из уже существующих
    пользователей с меткой курса (случай апгрейда «поставочной» БД)."""

    def test_seed_from_preexisting_users(self):
        import sqlite3
        path = _tmp_db()
        try:
            # «Поставочная» БД: старая форма users с меткой группы, без
            # структурных групп.
            with sqlite3.connect(path) as conn:
                conn.executescript(
                    'CREATE TABLE users ('
                    '  login TEXT PRIMARY KEY, password TEXT, FIO TEXT,'
                    '  "group" TEXT);'
                )
                conn.executemany(
                    'INSERT INTO users (login, password, FIO, "group") '
                    'VALUES (?,?,?,?)',
                    [("s1", "p", "С1", "КСБО-11-24"),
                     ("s2", "p", "С2", "КСБО-11-24"),
                     ("s3", "p", "С3", "ИСТ-21-24"),
                     ("t1", "p", "Т1", "")],  # без метки — не сеется
                )
                conn.commit()

            repo = Repository(path)  # прогоняет миграции, включая 003-seed
            by_name = {g.name: g for g in repo.list_groups()}
            self.assertEqual(set(by_name), {"КСБО-11-24", "ИСТ-21-24"})
            self.assertEqual(
                repo.list_group_members(by_name["КСБО-11-24"].id), ["s1", "s2"])
            self.assertEqual(
                repo.list_group_members(by_name["ИСТ-21-24"].id), ["s3"])

            # Идемпотентность: повторный прогон миграций не задваивает членство.
            from core.migrations import run_migrations
            with sqlite3.connect(path) as conn:
                run_migrations(conn)
            self.assertEqual(len(repo.list_groups()), 2)
            self.assertEqual(
                repo.list_group_members(by_name["КСБО-11-24"].id), ["s1", "s2"])
        finally:
            os.unlink(path)


class AdminApiTests(GroupsTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("s1", "p", "Студент", "", role="student")

    def test_create_group_and_list(self):
        out = groups_api.create_group(self.repo, name="Поток А",
                                      actor_login="root")
        self.assertEqual(out["name"], "Поток А")
        self.assertEqual(out["created_by"], "root")
        self.assertEqual(out["member_count"], 0)
        groups = groups_api.list_groups(self.repo)
        self.assertEqual([g["name"] for g in groups], ["Поток А"])

    def test_create_group_rejects_empty_and_duplicate(self):
        groups_api.create_group(self.repo, name="Поток А", actor_login="root")
        with self.assertRaisesRegex(groups_api.GroupActionError, "пустым"):
            groups_api.create_group(self.repo, name="  ", actor_login="root")
        with self.assertRaisesRegex(groups_api.GroupActionError, "существует"):
            groups_api.create_group(self.repo, name="Поток А",
                                    actor_login="root")

    def test_add_and_remove_member(self):
        g = groups_api.create_group(self.repo, name="Поток А",
                                    actor_login="root")
        gid = g["id"]
        out = groups_api.add_member(self.repo, group_id=gid, login="s1")
        self.assertEqual(out["members"], ["s1"])
        out = groups_api.remove_member(self.repo, group_id=gid, login="s1")
        self.assertEqual(out["members"], [])

    def test_add_member_rejects_unknown_group_and_user(self):
        with self.assertRaisesRegex(groups_api.GroupActionError, "не найдена"):
            groups_api.add_member(self.repo, group_id=999, login="s1")
        g = groups_api.create_group(self.repo, name="Поток А",
                                    actor_login="root")
        with self.assertRaisesRegex(groups_api.GroupActionError, "не найден"):
            groups_api.add_member(self.repo, group_id=g["id"], login="ghost")

    def test_assign_teacher_and_readview(self):
        g = groups_api.create_group(self.repo, name="Поток А",
                                    actor_login="root")
        gid = g["id"]
        out = groups_api.assign_teacher(self.repo, group_id=gid, login="alla")
        self.assertEqual(out["teachers"], ["alla"])
        mine = groups_api.teacher_groups(self.repo, teacher_login="alla")
        self.assertEqual([g["id"] for g in mine], [gid])
        # boris ничего не ведёт.
        self.assertEqual(
            groups_api.teacher_groups(self.repo, teacher_login="boris"), [])
        # Снятие назначения.
        out = groups_api.unassign_teacher(self.repo, group_id=gid, login="alla")
        self.assertEqual(out["teachers"], [])

    def test_assign_teacher_rejects_student(self):
        g = groups_api.create_group(self.repo, name="Поток А",
                                    actor_login="root")
        with self.assertRaisesRegex(groups_api.GroupActionError, "teacher"):
            groups_api.assign_teacher(self.repo, group_id=g["id"], login="s1")


class RouterTests(GroupsTestBase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import groups as groups_router

        app = FastAPI()
        app.include_router(groups_router.router)
        app.state.repo = self.repo
        return TestClient(app)

    def setUp(self):
        super().setUp()
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")

    def _h(self, login, role):
        return {"X-User-Id": login, "X-User-Role": role}

    def test_401_without_identity(self):
        self.assertEqual(self._client().get("/admin/groups").status_code, 401)

    def test_403_for_non_admin(self):
        r = self._client().get("/admin/groups", headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 403)

    def test_admin_crud_flow(self):
        c = self._client()
        r = c.post("/admin/groups", json={"name": "Поток А"},
                   headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200)
        gid = r.json()["id"]
        r = c.post(f"/admin/groups/{gid}/members", json={"login": "alla"},
                   headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["members"], ["alla"])
        r = c.post(f"/admin/groups/{gid}/teachers", json={"login": "alla"},
                   headers=self._h("root", "admin"))
        self.assertEqual(r.json()["teachers"], ["alla"])
        r = c.delete(f"/admin/groups/{gid}/members/alla",
                     headers=self._h("root", "admin"))
        self.assertEqual(r.json()["members"], [])

    def test_duplicate_group_returns_400(self):
        c = self._client()
        c.post("/admin/groups", json={"name": "Поток А"},
               headers=self._h("root", "admin"))
        r = c.post("/admin/groups", json={"name": "Поток А"},
                   headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 400)

    def test_groups_mine_for_teacher(self):
        c = self._client()
        r = c.post("/admin/groups", json={"name": "Поток А"},
                   headers=self._h("root", "admin"))
        gid = r.json()["id"]
        c.post(f"/admin/groups/{gid}/teachers", json={"login": "alla"},
               headers=self._h("root", "admin"))
        r = c.get("/groups/mine", headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([g["id"] for g in r.json()["groups"]], [gid])


if __name__ == "__main__":
    unittest.main()
