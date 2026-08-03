"""
Авторизация записи разделов через CRUD (`POST/DELETE /partitions`).

До этого правило было только у push'а синхронизации, а у CRUD не было
никакого: любой, кто дотянулся до сервиса, мог переписать или снести чужой
раздел, послав запрос мимо синка. Тесты ниже проверяют не «работает ли
создание», а именно это — что второй вход закрыт тем же правилом, что и
первый.

Отдельный класс сверяет ОБА входа на одних и тех же данных. Смысл не в
симметрии ради красоты: правило, продублированное в двух местах,
расходится — здесь оно одно (`core/content_authz.py`), и тест стережёт,
что оно осталось одним.

Приложение собирается из роутеров, а не импортом `generator_service.main`:
тот тянет всю сборку реестра, которой для проверки прав не нужно.

Запуск: python -m unittest core.test_partitions_authz -v
"""

from __future__ import annotations
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import sync_api  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import partitions as partitions_router  # noqa: E402


class PartitionAuthzTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("stud", "p", "Студент", "", role="student")

        # Три предмета: общий (без владельца) и по одному личному у каждого.
        self.shared = self.repo.ensure_subject(3, "Физика")
        self.alla_subject = self.repo.create_subject("Алгебра Аллы", "",
                                                     owner_user_id="alla")
        self.boris_subject = self.repo.create_subject("Матан Бориса", "",
                                                      owner_user_id="boris")

        app = FastAPI()
        errors.install(app)
        app.include_router(partitions_router.router)
        app.state.repo = self.repo
        # Пересборка реестра к правам отношения не имеет и тянет всю
        # сборку упражнений — заменяем пустышкой.
        partitions_router._rebuild = lambda _request: None   # noqa: SLF001
        self.client = TestClient(app)

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    # ---------- помощники ----------

    @staticmethod
    def _headers(login=None, role=None) -> dict:
        headers = {}
        if login is not None:
            headers["X-User-Id"] = login
        if role is not None:
            headers["X-User-Role"] = role
        return headers

    def _post(self, subject_id: int, name="Раздел", login=None, role=None):
        return self.client.post("/partitions", json={
            "subject_id": subject_id, "name": name,
            "constracted": 0, "generation_params": {}},
            headers=self._headers(login, role))

    def _delete(self, partition_id: int, login=None, role=None):
        return self.client.delete(f"/partitions/{partition_id}",
                                  headers=self._headers(login, role))

    def _seed(self, subject_id: int, name="Готовый") -> int:
        return self.repo.upsert_partition(subject_id, name, 0, {})


class UpsertAuthzTests(PartitionAuthzTestBase):
    def test_anonymous_cannot_create(self):
        resp = self._post(self.shared)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("идентичности", resp.json()["error"]["message"])
        self.assertEqual(self.repo.list_partitions_for_subject(self.shared), [])

    def test_student_cannot_create(self):
        # 403, а не 401: известно кто, и ему нельзя — входить бесполезно.
        resp = self._post(self.shared, login="stud", role="student")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("teacher", resp.json()["error"]["message"])

    def test_unknown_role_header_is_not_a_free_pass(self):
        # Роль приходит от релея; неизвестное значение обязано быть отказом,
        # а не «ну ладно».
        self.assertEqual(
            self._post(self.shared, login="alla", role="superuser").status_code,
            403)

    def test_missing_role_header_defaults_to_no_rights(self):
        # Заголовок роли может не доехать; умолчание обязано быть строгим.
        self.assertEqual(self._post(self.shared, login="alla").status_code, 403)

    def test_teacher_writes_into_the_shared_catalog(self):
        # Встроенные предметы преподавателю открыты — это сознательное
        # отступление от RBAC, ради него весь сценарий десктопа и живёт.
        resp = self._post(self.shared, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.json()["partition_id"], 0)

    def test_teacher_writes_into_own_subject(self):
        self.assertEqual(
            self._post(self.alla_subject, login="alla", role="teacher"
                       ).status_code, 200)

    def test_teacher_cannot_write_into_someone_elses_subject(self):
        resp = self._post(self.boris_subject, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("другому владельцу", resp.json()["error"]["message"])
        self.assertEqual(
            self.repo.list_partitions_for_subject(self.boris_subject), [])

    def test_grant_does_not_give_write_access(self):
        # Выдача даёт право ВИДЕТЬ. Это и есть та дыра, ради которой правило
        # писалось: чужой предмет доезжает до преподавателя, и без проверки
        # доезжал бы вместе с правом его переписать.
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        self.assertEqual(
            self._post(self.boris_subject, login="alla", role="teacher"
                       ).status_code, 403)

    def test_admin_writes_anywhere(self):
        for subject_id in (self.shared, self.alla_subject, self.boris_subject):
            self.assertEqual(
                self._post(subject_id, name=f"Р{subject_id}",
                           login="root", role="admin").status_code, 200)

    def test_role_header_is_case_insensitive(self):
        self.assertEqual(
            self._post(self.shared, login="alla", role="Teacher").status_code,
            200)


class DeleteAuthzTests(PartitionAuthzTestBase):
    def test_anonymous_cannot_delete(self):
        pid = self._seed(self.shared)
        self.assertEqual(self._delete(pid).status_code, 401)
        self.assertIsNotNone(self.repo.get_partition(pid))

    def test_student_cannot_delete(self):
        pid = self._seed(self.shared)
        self.assertEqual(self._delete(pid, login="stud", role="student"
                                      ).status_code, 403)
        self.assertIsNotNone(self.repo.get_partition(pid))

    def test_teacher_cannot_delete_from_someone_elses_subject(self):
        pid = self._seed(self.boris_subject)
        resp = self._delete(pid, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("другому владельцу", resp.json()["error"]["message"])
        self.assertIsNotNone(self.repo.get_partition(pid))

    def test_teacher_deletes_own(self):
        pid = self._seed(self.alla_subject)
        self.assertEqual(self._delete(pid, login="alla", role="teacher"
                                      ).status_code, 200)

    def test_admin_deletes_anything(self):
        pid = self._seed(self.boris_subject)
        self.assertEqual(self._delete(pid, login="root", role="admin"
                                      ).status_code, 200)

    def test_missing_partition_is_404_for_the_authorized(self):
        self.assertEqual(self._delete(999999, login="alla", role="teacher"
                                      ).status_code, 404)

    def test_identity_is_checked_before_existence(self):
        # Иначе аноним перебором id выяснял бы, какие разделы существуют:
        # 404 против 403 — это ответ на вопрос, который ему не задавали.
        self.assertEqual(self._delete(999999).status_code, 401)


class BothWritePathsAgreeTests(PartitionAuthzTestBase):
    """
    Одно правило на два входа. Расхождение здесь означает, что кто-то
    поправил один путь и забыл про второй, — ровно то, из-за чего дыра и
    появилась.
    """

    def _push(self, subject_id: int, actor, role: str):
        return sync_api.push(
            self.repo, device_id="dev-1", user_id=actor, role=role,
            changed_entities=[{
                "kind": "partition", "id": None, "local_ref": "1",
                "base_version": 0,
                "data": {"subject_id": subject_id,
                         "partition_name": "Через синк",
                         "constracted": 0, "generation_parametrs": "{}"}}])

    def _refused_by_sync(self, subject_id: int, actor, role: str) -> bool:
        out = self._push(subject_id, actor, role)
        return bool(out["conflicts"]) and out["conflicts"][0].get("forbidden")

    def _refused_by_crud(self, subject_id: int, actor, role: str) -> bool:
        return self._post(subject_id, name="Через CRUD",
                          login=actor, role=role).status_code in (401, 403)

    def test_same_verdict_for_every_case(self):
        cases = [
            ("аноним в общий",        self.shared,       None,    "student"),
            ("студент в общий",       self.shared,       "stud",  "student"),
            ("преподаватель в общий", self.shared,       "alla",  "teacher"),
            ("преподаватель к себе",  self.alla_subject, "alla",  "teacher"),
            ("преподаватель в чужой", self.boris_subject, "alla", "teacher"),
            ("админ в чужой",         self.boris_subject, "root", "admin"),
        ]
        for label, subject_id, actor, role in cases:
            with self.subTest(label):
                self.assertEqual(
                    self._refused_by_sync(subject_id, actor, role),
                    self._refused_by_crud(subject_id, actor, role),
                    f"пути записи разошлись на случае «{label}»")


if __name__ == "__main__":
    unittest.main()
