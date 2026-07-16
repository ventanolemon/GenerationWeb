"""
Тесты домашек (core/assignments_api) — headless, свежая SQLite на каждый тест.

Запуск: python -m unittest core.test_assignments_api  (из корня монорепо)
"""

from __future__ import annotations
import os
import tempfile
import unittest

from core import assignments_api
from core.repository import Repository


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


class AssignmentsTestBase(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        self.repo = Repository(self.db)
        # Преподаватели, студенты.
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("s1", "p", "Студент 1", "")
        # Предметы: свой у Аллы + системный.
        self.sys_subj = self.repo.ensure_subject(1, "Физика", "Физика")
        self.alla_subj = self.repo.create_subject("Курс Аллы", "x",
                                                  owner_user_id="alla")
        self.boris_subj = self.repo.create_subject("Курс Бориса", "x",
                                                   owner_user_id="boris")
        self.p_alla = self.repo.upsert_partition(self.alla_subj, "Аллы", 4, {})
        self.p_sys = self.repo.upsert_partition(self.sys_subj, "Общий", 4, {})
        self.p_boris = self.repo.upsert_partition(self.boris_subj, "Бориса",
                                                  4, {})
        # Группа, которую ведёт Алла; в ней студент s1.
        self.g = self.repo.create_group("КСБО-11-24", created_by="root")
        self.repo.add_group_member(self.g, "s1")
        self.repo.assign_teacher_to_group("alla", self.g)
        # Группа, которую Алла НЕ ведёт.
        self.g_other = self.repo.create_group("ИСТ-21-24", created_by="root")

    def tearDown(self):
        os.unlink(self.db)


class CreateGuardrailTests(AssignmentsTestBase):
    def test_teacher_assigns_own_task_to_taught_group(self):
        out = assignments_api.create(
            self.repo, actor_login="alla", role="teacher",
            partition_id=self.p_alla, group_id=self.g, due_at=1000.0)
        self.assertEqual(out["partition_id"], self.p_alla)
        self.assertEqual(out["group_id"], self.g)
        self.assertEqual(out["assigned_by"], "alla")
        self.assertEqual(out["group_name"], "КСБО-11-24")
        self.assertEqual(out["partition_name"], "Аллы")

    def test_teacher_can_assign_system_task(self):
        # Системный предмет виден всем → задачу выдать можно.
        out = assignments_api.create(
            self.repo, actor_login="alla", role="teacher",
            partition_id=self.p_sys, group_id=self.g)
        self.assertEqual(out["partition_id"], self.p_sys)

    def test_reject_task_from_invisible_subject(self):
        with self.assertRaisesRegex(assignments_api.AssignmentActionError,
                                    "недоступного"):
            assignments_api.create(
                self.repo, actor_login="alla", role="teacher",
                partition_id=self.p_boris, group_id=self.g)

    def test_reject_group_not_taught(self):
        with self.assertRaisesRegex(assignments_api.AssignmentActionError,
                                    "не ведёте"):
            assignments_api.create(
                self.repo, actor_login="alla", role="teacher",
                partition_id=self.p_alla, group_id=self.g_other)

    def test_reject_student(self):
        with self.assertRaisesRegex(assignments_api.AssignmentActionError,
                                    "преподаватель"):
            assignments_api.create(
                self.repo, actor_login="s1", role="student",
                partition_id=self.p_alla, group_id=self.g)

    def test_admin_assigns_anything(self):
        out = assignments_api.create(
            self.repo, actor_login="root", role="admin",
            partition_id=self.p_boris, group_id=self.g_other)
        self.assertEqual(out["partition_id"], self.p_boris)

    def test_reissue_updates_due_not_duplicates(self):
        a1 = assignments_api.create(
            self.repo, actor_login="alla", role="teacher",
            partition_id=self.p_alla, group_id=self.g, due_at=1000.0)
        a2 = assignments_api.create(
            self.repo, actor_login="alla", role="teacher",
            partition_id=self.p_alla, group_id=self.g, due_at=2000.0)
        self.assertEqual(a1["id"], a2["id"])
        self.assertEqual(a2["due_at"], 2000.0)
        self.assertEqual(
            len(assignments_api.list_teaching(self.repo, actor_login="alla")), 1)


class ReadTests(AssignmentsTestBase):
    def test_student_sees_homework_for_their_groups(self):
        assignments_api.create(self.repo, actor_login="alla", role="teacher",
                               partition_id=self.p_alla, group_id=self.g)
        mine = assignments_api.list_mine(self.repo, actor_login="s1")
        self.assertEqual([a["partition_id"] for a in mine], [self.p_alla])
        self.assertEqual(mine[0]["subject_name"], "Курс Аллы")

    def test_student_not_in_group_sees_nothing(self):
        assignments_api.create(self.repo, actor_login="alla", role="teacher",
                               partition_id=self.p_alla, group_id=self.g)
        self.repo.create_user("s2", "p", "Другой", "")
        self.assertEqual(
            assignments_api.list_mine(self.repo, actor_login="s2"), [])

    def test_deleted_partition_hidden_from_homework(self):
        assignments_api.create(self.repo, actor_login="alla", role="teacher",
                               partition_id=self.p_alla, group_id=self.g)
        self.repo.delete_partition(self.p_alla)
        self.assertEqual(
            assignments_api.list_mine(self.repo, actor_login="s1"), [])

    def test_teaching_lists_only_own(self):
        assignments_api.create(self.repo, actor_login="alla", role="teacher",
                               partition_id=self.p_alla, group_id=self.g)
        self.assertEqual(
            len(assignments_api.list_teaching(self.repo, actor_login="alla")), 1)
        self.assertEqual(
            assignments_api.list_teaching(self.repo, actor_login="boris"), [])


class DeleteTests(AssignmentsTestBase):
    def test_author_deletes(self):
        a = assignments_api.create(self.repo, actor_login="alla",
                                   role="teacher", partition_id=self.p_alla,
                                   group_id=self.g)
        assignments_api.delete(self.repo, actor_login="alla", role="teacher",
                               assignment_id=a["id"])
        self.assertEqual(
            assignments_api.list_teaching(self.repo, actor_login="alla"), [])

    def test_other_teacher_cannot_delete(self):
        a = assignments_api.create(self.repo, actor_login="alla",
                                   role="teacher", partition_id=self.p_alla,
                                   group_id=self.g)
        with self.assertRaisesRegex(assignments_api.AssignmentActionError,
                                    "собственную"):
            assignments_api.delete(self.repo, actor_login="boris",
                                   role="teacher", assignment_id=a["id"])

    def test_admin_deletes_any(self):
        a = assignments_api.create(self.repo, actor_login="alla",
                                   role="teacher", partition_id=self.p_alla,
                                   group_id=self.g)
        out = assignments_api.delete(self.repo, actor_login="root",
                                     role="admin", assignment_id=a["id"])
        self.assertEqual(out["deleted"], a["id"])


class RouterTests(AssignmentsTestBase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import assignments as ar

        app = FastAPI()
        app.include_router(ar.router)
        app.state.repo = self.repo
        return TestClient(app)

    def _h(self, login, role):
        return {"X-User-Id": login, "X-User-Role": role}

    def test_401_without_identity(self):
        r = self._client().get("/assignments/mine")
        self.assertEqual(r.status_code, 401)

    def test_create_and_student_sees(self):
        c = self._client()
        r = c.post("/assignments",
                   json={"partition_id": self.p_alla, "group_id": self.g,
                         "due_at": 1000.0},
                   headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 200)
        r = c.get("/assignments/mine", headers=self._h("s1", "student"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["assignments"]), 1)

    def test_guardrail_returns_400(self):
        r = self._client().post(
            "/assignments",
            json={"partition_id": self.p_boris, "group_id": self.g},
            headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 400)

    def test_delete_flow(self):
        c = self._client()
        r = c.post("/assignments",
                   json={"partition_id": self.p_alla, "group_id": self.g},
                   headers=self._h("alla", "teacher"))
        aid = r.json()["id"]
        r = c.delete(f"/assignments/{aid}", headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 200)
        r = c.get("/assignments/teaching", headers=self._h("alla", "teacher"))
        self.assertEqual(r.json()["assignments"], [])


if __name__ == "__main__":
    unittest.main()
