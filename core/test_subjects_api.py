"""
Предметы: завести, переименовать, удалить — и не увидеть чужое.

До этого предмет НЕЛЬЗЯ было создать через продукт вовсе, а витрина
`GET /subjects` отдавала все предметы развёртывания, включая чужую
организацию. Здесь проверяется и то, и другое.

Запуск:
    python -m unittest core.test_subjects_api
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import auth_sessions, organizations_api, subjects_api  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import subjects as subjects_router  # noqa: E402
from core.tmpdb import temp_path  # noqa: E402


class _StubRegistry:
    def has(self, _p):
        return False


class SubjectsTestBase(unittest.TestCase):
    """
    Две организации. root — superuser в «Физфаке», alla — teacher там же,
    clara — teacher «Химфака».
    """

    def setUp(self):
        self.db_path = temp_path(suffix=".db")
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        organizations_api.ensure_bootstrapped(self.repo)
        self.phys = self.repo.default_organization_id()

        self.chem = self.repo.create_organization("Химфак")
        self.repo.create_user("clara", "p", "Клара", "", role="teacher",
                              organization_id=self.chem)
        self.repo.create_user("stud", "p", "Студент", "",
                              organization_id=self.phys)

        self.builtin = self.repo.create_subject("Встроенный", "Встроенный")
        self.chem_subject = self.repo.create_subject(
            "Химия Клары", "Химия", owner_user_id="clara")
        self.repo.set_subject_organization(self.chem_subject, self.chem)

        app = FastAPI()
        errors.install(app)
        app.include_router(subjects_router.router)
        app.state.repo = self.repo
        app.state.registry = _StubRegistry()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _h(self, login):
        token = auth_sessions.issue(self.repo, login)["token"]
        return {"Authorization": f"Bearer {token}"}

    def _names(self, login):
        body = self.client.get("/subjects/manage",
                               headers=self._h(login)).json()
        return sorted(s["name"] for s in body["subjects"])


# ---------- Витрина ----------

class VisibilityTests(SubjectsTestBase):
    def test_foreign_organization_subject_is_not_listed(self):
        """
        Ровно та утечка, ради которой чинилась витрина: `GET /subjects`
        отдавал всё подряд, и «Химия Клары» попадала в выпадающий список
        преподавателя другой организации.
        """
        self.assertNotIn("Химия Клары", self._names("alla"))
        self.assertIn("Химия Клары", self._names("clara"))

    def test_builtin_crosses_the_boundary(self):
        for login in ("alla", "clara"):
            self.assertIn("Встроенный", self._names(login))

    def test_plain_list_is_scoped_too(self):
        # Списком пользуется выпадающий список фронта — он обязан
        # совпадать с /manage, иначе экраны разъедутся.
        names = [s["name"] for s in
                 self.client.get("/subjects", headers=self._h("alla")).json()]
        self.assertNotIn("Химия Клары", names)

    def test_guest_sees_only_builtin(self):
        names = [s["name"] for s in self.client.get("/subjects").json()]
        self.assertEqual(names, ["Встроенный"])


# ---------- Создание ----------

class CreateTests(SubjectsTestBase):
    def test_teacher_creates_their_own(self):
        r = self.client.post("/subjects", json={"name": "Оптика"},
                             headers=self._h("alla"))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["owner"], "alla")
        self.assertEqual(body["organization_id"], self.phys)
        self.assertIn("Оптика", self._names("alla"))

    def test_creation_does_not_leak_to_a_foreign_organization(self):
        self.client.post("/subjects", json={"name": "Оптика"},
                         headers=self._h("alla"))
        self.assertNotIn("Оптика", self._names("clara"))

    def test_student_cannot(self):
        r = self.client.post("/subjects", json={"name": "Мой"},
                             headers=self._h("stud"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("не заводит предметы", r.json()["detail"])

    def test_guest_cannot(self):
        self.assertEqual(
            self.client.post("/subjects", json={"name": "Мой"}).status_code,
            401)

    def test_own_duplicate_is_refused(self):
        self.client.post("/subjects", json={"name": "Оптика"},
                         headers=self._h("alla"))
        r = self.client.post("/subjects", json={"name": "Оптика"},
                             headers=self._h("alla"))
        self.assertEqual(r.status_code, 400)

    def test_same_name_for_a_different_owner_is_fine(self):
        # У каждого своё личное хранилище; тёзка чужого предмета не мешает.
        self.client.post("/subjects", json={"name": "Оптика"},
                         headers=self._h("alla"))
        r = self.client.post("/subjects", json={"name": "Оптика"},
                             headers=self._h("clara"))
        self.assertEqual(r.status_code, 200, r.text)

    def test_creation_bumps_the_scope_epoch(self):
        before = self.repo.scope_version("alla")
        self.client.post("/subjects", json={"name": "Оптика"},
                         headers=self._h("alla"))
        self.assertGreater(self.repo.scope_version("alla"), before)


# ---------- Правка и удаление ----------

class EditTests(SubjectsTestBase):
    def _own(self, login="alla", name="Оптика"):
        return self.client.post("/subjects", json={"name": name},
                                headers=self._h(login)).json()["id"]

    def test_owner_renames(self):
        sid = self._own()
        r = self.client.patch(f"/subjects/{sid}", json={"name": "Волны"},
                              headers=self._h("alla"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Волны", self._names("alla"))

    def test_stranger_cannot_rename(self):
        sid = self._own()
        r = self.client.patch(f"/subjects/{sid}", json={"name": "Захват"},
                              headers=self._h("clara"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("другому владельцу", r.json()["detail"])

    def test_builtin_is_only_for_the_deployment_admin(self):
        r = self.client.patch(f"/subjects/{self.builtin}",
                              json={"name": "Переименован"},
                              headers=self._h("alla"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("администратор развёртывания", r.json()["detail"])

        ok = self.client.patch(f"/subjects/{self.builtin}",
                               json={"name": "Переименован"},
                               headers=self._h("root"))
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_empty_subject_is_deleted(self):
        sid = self._own()
        r = self.client.delete(f"/subjects/{sid}", headers=self._h("alla"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("Оптика", self._names("alla"))

    def test_non_empty_subject_is_refused_with_a_count(self):
        """
        Каскад сносил бы разделы, приехавшие в том числе с чужого
        десктопа. Отказ называет число — человек решает сам.
        """
        sid = self._own()
        self.repo.upsert_partition(sid, "Раздел", 0, {})
        r = self.client.delete(f"/subjects/{sid}", headers=self._h("alla"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("1", r.json()["detail"])
        self.assertIn("Оптика", self._names("alla"))

    def test_deletion_is_a_tombstone_not_a_wipe(self):
        # Физическое удаление не доехало бы до десктопов, и предмет
        # воскрес бы при следующем push'е.
        sid = self._own()
        self.client.delete(f"/subjects/{sid}", headers=self._h("alla"))
        with self.repo._connect() as conn:
            row = conn.execute(
                "SELECT deleted_at, row_version FROM Subjects WHERE id = ?",
                (sid,)).fetchone()
        self.assertIsNotNone(row[0], "строка удалена физически")
        self.assertGreater(row[1], 1, "row_version не поднят")


if __name__ == "__main__":
    unittest.main()
