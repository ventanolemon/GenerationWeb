"""
Авторизация ЧТЕНИЯ авторского содержимого разделов.

`GET /partitions/{id}` отдаёт `generation_params` — сам граф или конфиг
генератора, то есть авторскую работу преподавателя. Читался он по id кем
угодно, кто дотянулся до сервиса.

Правило (`content_authz.check_authoring_read`) не копия правила записи, и
тесты проверяют оба отличия:

  * **мягче по владельцу** — выданный чужой предмет читать можно. Иначе
    веб разошёлся бы с синком, который такому преподавателю этот граф уже
    присылает, а расхождение путей — та самая причина, по которой дыра на
    записи вообще появилась;
  * **строже по роли** — решающему «кишки» задания не нужны.

Отдельный класс сверяет, что скоуп чтения совпадает со скоупом pull'а:
это единственное, что у двух путей обязано быть общим.

И отдельный — что отказ неотличим от отсутствия. 404 против 403 здесь не
косметика: id последовательные, и разница в ответе превращается в
инструмент перебора.

Запуск: python -m unittest core.test_partitions_read_authz -v
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

from core import content_authz, sync_api  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import partitions as partitions_router  # noqa: E402


class ReadAuthzTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("stud", "p", "Студент", "", role="student")

        self.shared = self.repo.ensure_subject(3, "Физика")
        self.alla_subject = self.repo.create_subject("Алгебра Аллы", "",
                                                     owner_user_id="alla")
        self.boris_subject = self.repo.create_subject("Матан Бориса", "",
                                                      owner_user_id="boris")
        self.alla_part = self.repo.upsert_partition(
            self.alla_subject, "Её раздел", 4, {"nodes": [{"type": "formula"}]})
        self.boris_part = self.repo.upsert_partition(
            self.boris_subject, "Его раздел", 4, {"nodes": [{"type": "secret"}]})
        self.shared_part = self.repo.upsert_partition(
            self.shared, "Общий раздел", 1, {"formula": "a+b"})

        app = FastAPI()
        errors.install(app)
        app.include_router(partitions_router.router)
        app.state.repo = self.repo
        partitions_router._rebuild = lambda _request: None     # noqa: SLF001
        self.client = TestClient(app)

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    @staticmethod
    def _headers(login=None, role=None) -> dict:
        headers = {}
        if login is not None:
            headers["X-User-Id"] = login
        if role is not None:
            headers["X-User-Role"] = role
        return headers

    def _get(self, partition_id: int, login=None, role=None):
        return self.client.get(f"/partitions/{partition_id}",
                               headers=self._headers(login, role))

    def _candidates(self, subject_id: int, login=None, role=None):
        return self.client.get(f"/partitions/candidates/{subject_id}",
                               headers=self._headers(login, role))


class AuthoringReadTests(ReadAuthzTestBase):
    def test_anonymous_cannot_read_the_graph(self):
        resp = self._get(self.alla_part)
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("generation_params", resp.text)

    def test_student_cannot_read_the_graph(self):
        # Решающему «кишки» задания не нужны, а угадывать по ним помогают.
        resp = self._get(self.shared_part, login="stud", role="student")
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn("formula", resp.text)

    def test_owner_reads_own(self):
        resp = self._get(self.alla_part, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["generation_params"],
                         {"nodes": [{"type": "formula"}]})

    def test_teacher_reads_the_shared_catalog(self):
        self.assertEqual(
            self._get(self.shared_part, login="alla", role="teacher"
                      ).status_code, 200)

    def test_foreign_subject_is_not_readable(self):
        resp = self._get(self.boris_part, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("secret", resp.text)

    def test_grant_opens_reading_although_it_does_not_open_writing(self):
        # Главное отличие от правила записи. Синк выданный граф уже
        # присылает — запрет здесь развёл бы веб и синк.
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        self.assertEqual(
            self._get(self.boris_part, login="alla", role="teacher"
                      ).status_code, 200)
        self.assertEqual(
            self.client.post("/partitions", json={
                "subject_id": self.boris_subject, "name": "Влезу",
                "constracted": 0, "generation_params": {}},
                headers=self._headers("alla", "teacher")).status_code, 403)

    def test_admin_reads_anything(self):
        for pid in (self.alla_part, self.boris_part, self.shared_part):
            self.assertEqual(
                self._get(pid, login="root", role="admin").status_code, 200)

    def test_missing_role_header_defaults_to_no_rights(self):
        self.assertEqual(self._get(self.alla_part, login="alla").status_code,
                         403)


class RefusalIsIndistinguishableTests(ReadAuthzTestBase):
    """
    Id последовательные. Если «нет такого» и «есть, но не ваш» отвечают
    по-разному, перебор превращается в карту чужих разделов.
    """

    def test_same_status_and_same_body(self):
        missing = self._get(999999, login="alla", role="teacher")
        foreign = self._get(self.boris_part, login="alla", role="teacher")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(missing.json()["error"]["message"],
                         foreign.json()["error"]["message"])

    def test_identity_is_checked_before_existence(self):
        self.assertEqual(self._get(999999).status_code, 401)


class CandidatesTests(ReadAuthzTestBase):
    def setUp(self):
        super().setUp()
        # «Дочерние» предметы: parent_name == имя родителя. Один — Аллы,
        # другой — Бориса, оба дети общей «Физики».
        self.child_alla = self.repo.create_subject("Физика-1", "Физика",
                                                   owner_user_id="alla")
        self.child_boris = self.repo.create_subject("Физика-2", "Физика",
                                                    owner_user_id="boris")
        self.repo.upsert_partition(self.child_alla, "Её дочерний", 0, {})
        self.repo.upsert_partition(self.child_boris, "Его дочерний", 0, {})

    def _sibling_names(self, resp) -> set:
        return {p["name"] for p in resp.json()["siblings"]}

    def test_anonymous_is_refused(self):
        self.assertEqual(self._candidates(self.shared).status_code, 401)

    def test_student_is_refused(self):
        self.assertEqual(
            self._candidates(self.shared, login="stud", role="student"
                             ).status_code, 403)

    def test_siblings_outside_the_scope_are_filtered_out(self):
        # Проверку легко обойти с другой стороны: не «покажи чужой раздел»,
        # а «покажи список, в котором он окажется».
        resp = self._candidates(self.shared, login="alla", role="teacher")
        self.assertEqual(resp.status_code, 200)
        names = self._sibling_names(resp)
        self.assertIn("Её дочерний", names)
        self.assertNotIn("Его дочерний", names)

    def test_admin_sees_all_siblings(self):
        names = self._sibling_names(
            self._candidates(self.shared, login="root", role="admin"))
        self.assertEqual(names, {"Её дочерний", "Его дочерний"})

    def test_grant_brings_a_sibling_back(self):
        self.repo.replace_subject_grants(
            "alla", [self.shared, self.alla_subject, self.child_alla,
                     self.child_boris])
        names = self._sibling_names(
            self._candidates(self.shared, login="alla", role="teacher"))
        self.assertIn("Его дочерний", names)

    def test_foreign_subject_is_not_enumerable(self):
        self.assertEqual(
            self._candidates(self.boris_subject, login="alla", role="teacher"
                             ).status_code, 404)


class ReadScopeMatchesPullTests(ReadAuthzTestBase):
    """
    Скоуп чтения обязан совпадать со скоупом pull'а: это единственное, что у
    веба и синка общее, и расхождение здесь означало бы, что через один путь
    видно то, чего не видно через другой.
    """

    def test_same_scope_for_every_actor(self):
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        for actor, role in (("alla", "teacher"), ("boris", "teacher"),
                            ("root", "admin"), ("stud", "student")):
            with self.subTest(actor):
                self.assertEqual(
                    sync_api.visible_scope(self.repo, actor, role),
                    sorted(content_authz.readable_subject_ids(
                        self.repo, actor, role)))

    def test_readable_subject_is_readable_through_http(self):
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        scope = content_authz.readable_subject_ids(self.repo, "alla",
                                                   "teacher")
        for subject_id, partition_id in ((self.boris_subject,
                                          self.boris_part),
                                         (self.alla_subject, self.alla_part)):
            with self.subTest(subject_id):
                expected = 200 if subject_id in scope else 404
                self.assertEqual(
                    self._get(partition_id, login="alla", role="teacher"
                              ).status_code, expected)


if __name__ == "__main__":
    unittest.main()
