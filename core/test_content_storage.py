"""
Хранилища контента: личное преподавателя ↔ общее.

Проверяем то, что легко сделать неправильно:

  * перенос поднимает эпохи скоупа ТЕХ, кого он затронул — иначе изменение
    до десктопов не доедет: у потерявшего предмет версия строки не меняется
    в его пользу, область считается на сервере, а не в дифе;
  * уход в личное снимает публичный доступ — иначе ключ стороннего
    приложения продолжал бы отдавать наружу личный контент преподавателя;
  * возврат в общее публичный доступ НЕ восстанавливает: выдача была
    решением администратора, а не свойством предмета;
  * предмет, приехавший с десктопа преподавателя, ложится в ЕГО личное
    хранилище — владельца назначает сервер, клиент подменить не может;
  * перенос обязан менять row_version, иначе синк о нём не узнает.

Запуск: python -m unittest core.test_content_storage -v
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import (api_clients, auth_sessions, content_api,  # noqa: E402
                  organizations_api, sync_api)
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import admin_content  # noqa: E402


class StorageTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        # Тот же шаг, что делает сервис при старте: развёртыванию нужен
        # администратор развёртывания (is_superuser), иначе пакеты, ключи,
        # выпуски и публичный API закрыты для всех. Роль admin теперь
        # означает «админ своей организации» — см. §8.2.
        organizations_api.ensure_bootstrapped(self.repo)
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("stud", "p", "Студент", "КСБО-11")

        self.shared = self.repo.ensure_subject(3, "Физика")          # общее
        self.personal = self.repo.create_subject("Курс Аллы", "Курс Аллы",
                                                 owner_user_id="alla")
        self.repo.upsert_partition(self.personal, "Раздел Аллы", 0, {})

        app = FastAPI()
        errors.install(app)
        app.include_router(admin_content.router)
        app.state.repo = self.repo
        self.http = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    def _row_version(self, subject_id):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT row_version FROM Subjects WHERE id = ?",
                                (subject_id,)).fetchone()[0]

    def _h(self, login, role=None):
        """
        Заголовки личности: настоящая сессия, а не заявление.

        Роль больше не передаётся — сервер читает её из БД по токену
        (GEN_TRUST_IDENTITY_HEADERS снят). Параметр оставлен, чтобы не
        переписывать сотни вызовов, и игнорируется: если он расходится с
        БД, прав это не добавляет — в этом и была суть перехода.
        """
        token = auth_sessions.issue(self.repo, login)["token"]
        return {"Authorization": f"Bearer {token}"}


# ---------- Модель хранилищ ----------

class StorageModelTests(StorageTestBase):
    def test_owner_is_the_storage(self):
        out = content_api.overview(self.repo)
        by_id = {s["id"]: s for s in out["subjects"]}
        self.assertEqual(by_id[self.shared]["storage"], "shared")
        self.assertEqual(by_id[self.personal]["storage"], "personal")
        self.assertEqual(by_id[self.personal]["owner"], "alla")
        self.assertEqual(by_id[self.personal]["partition_count"], 1)

    def test_list_mine_shows_only_own(self):
        mine = content_api.list_mine(self.repo, actor_login="alla")
        self.assertEqual([s["id"] for s in mine["subjects"]], [self.personal])
        self.assertEqual(
            content_api.list_mine(self.repo, actor_login="boris")["subjects"],
            [])

    def test_subject_pushed_from_desktop_lands_in_authors_personal(self):
        """Ровно тот путь, которым преподаватель отдаёт свой предмет серверу."""
        out = sync_api.push(
            self.repo, device_id="d", user_id="boris", role="teacher",
            changed_entities=[{"kind": "subject", "id": None,
                               "base_version": 0,
                               "data": {"subject_name": "Курс Бориса",
                                        # клиент заявляет чужого владельца…
                                        "owner_user_id": "alla"}}])
        new_id = out["accepted"][0]["id"]
        # …сервер ставит автора запроса.
        self.assertEqual(self.repo.subject_owner(new_id), "boris")
        mine = content_api.list_mine(self.repo, actor_login="boris")
        self.assertEqual([s["id"] for s in mine["subjects"]], [new_id])


# ---------- Перенос ----------

class TransferTests(StorageTestBase):
    def test_publish_moves_personal_to_shared(self):
        out = content_api.publish(self.repo, subject_id=self.personal,
                                  actor_login="root")
        self.assertEqual((out["from"], out["to"]), ("personal", "shared"))
        self.assertIsNone(self.repo.subject_owner(self.personal))

    def test_assign_moves_shared_to_personal(self):
        out = content_api.assign_to(self.repo, subject_id=self.shared,
                                    login="boris", actor_login="root")
        self.assertEqual((out["from"], out["to"]), ("shared", "personal"))
        self.assertEqual(self.repo.subject_owner(self.shared), "boris")

    def test_transfer_between_personals(self):
        content_api.assign_to(self.repo, subject_id=self.personal,
                              login="boris", actor_login="root")
        self.assertEqual(self.repo.subject_owner(self.personal), "boris")

    def test_partitions_follow_the_subject(self):
        # Своего владельца у партиции нет — права выводятся из предмета.
        content_api.publish(self.repo, subject_id=self.personal,
                            actor_login="root")
        parts = self.repo.list_partitions_for_subject(self.personal)
        self.assertEqual(len(parts), 1)
        self.assertTrue(self.repo.can_edit_subject("root", "admin",
                                                   self.personal))

    def test_transfer_bumps_row_version_so_sync_notices(self):
        before = self._row_version(self.personal)
        content_api.publish(self.repo, subject_id=self.personal,
                            actor_login="root")
        self.assertGreater(self._row_version(self.personal), before)

    def test_noop_transfer_is_rejected(self):
        with self.assertRaisesRegex(content_api.ContentActionError,
                                    "переносить нечего"):
            content_api.publish(self.repo, subject_id=self.shared,
                                actor_login="root")

    def test_unknown_subject_and_owner_rejected(self):
        with self.assertRaisesRegex(content_api.ContentActionError, "9999"):
            content_api.publish(self.repo, subject_id=9999, actor_login="root")
        with self.assertRaisesRegex(content_api.ContentActionError, "не найден"):
            content_api.assign_to(self.repo, subject_id=self.shared,
                                  login="нет-такого", actor_login="root")

    def test_student_has_no_personal_storage(self):
        with self.assertRaisesRegex(content_api.ContentActionError, "роль"):
            content_api.assign_to(self.repo, subject_id=self.shared,
                                  login="stud", actor_login="root")


# ---------- Эпохи скоупа ----------

class ScopeEpochTests(StorageTestBase):
    def _epochs(self):
        return {login: self.repo.scope_version(login)
                for login in ("alla", "boris", "stud")}

    def test_publishing_bumps_every_teacher(self):
        # Общее видно всем без явных выдач — появление там меняет набор
        # у каждого преподавателя.
        before = self._epochs()
        content_api.publish(self.repo, subject_id=self.personal,
                            actor_login="root")
        after = self._epochs()
        self.assertEqual(after["alla"], before["alla"] + 1)
        self.assertEqual(after["boris"], before["boris"] + 1)
        self.assertEqual(after["stud"], before["stud"],
                         "студента выдачи не касаются")

    def test_taking_from_shared_bumps_every_teacher(self):
        before = self._epochs()
        content_api.assign_to(self.repo, subject_id=self.shared,
                              login="boris", actor_login="root")
        after = self._epochs()
        self.assertEqual(after["alla"], before["alla"] + 1,
                         "Алла потеряла предмет из виду — обязана пересобраться")
        self.assertEqual(after["boris"], before["boris"] + 1)

    def test_personal_to_personal_bumps_only_the_two(self):
        self.repo.create_user("clara", "p", "Клара", "", role="teacher")
        before_clara = self.repo.scope_version("clara")
        before = self._epochs()
        content_api.assign_to(self.repo, subject_id=self.personal,
                              login="boris", actor_login="root")
        after = self._epochs()
        self.assertEqual(after["alla"], before["alla"] + 1)
        self.assertEqual(after["boris"], before["boris"] + 1)
        self.assertEqual(self.repo.scope_version("clara"), before_clara,
                         "непричастных не трогаем")

    def test_transferred_subject_leaves_the_losers_pull_scope(self):
        """Сквозная проверка: после переноса предмет исчезает из скоупа."""
        self.assertIn(self.shared,
                      sync_api.visible_scope(self.repo, "alla", "teacher"))
        content_api.assign_to(self.repo, subject_id=self.shared,
                              login="boris", actor_login="root")
        self.assertNotIn(self.shared,
                         sync_api.visible_scope(self.repo, "alla", "teacher"))
        self.assertIn(self.shared,
                      sync_api.visible_scope(self.repo, "boris", "teacher"))


# ---------- Публичный доступ ----------

class PublicAccessTests(StorageTestBase):
    def setUp(self):
        super().setUp()
        self.client_id = self.repo.create_api_client("Интегратор", "root", 1000)

    def test_going_personal_revokes_explicit_api_access(self):
        api_clients.set_subjects(self.repo, client_id=self.client_id,
                                 subject_ids=[self.shared])
        out = content_api.assign_to(self.repo, subject_id=self.shared,
                                    login="alla", actor_login="root")
        self.assertEqual(out["api_access_revoked_from"], ["Интегратор"])
        self.assertNotIn(self.shared,
                         self.repo.api_client_subject_ids(self.client_id))

    def test_returning_to_shared_does_not_restore_the_grant(self):
        # Выдача была решением админа, а не свойством предмета.
        api_clients.set_subjects(self.repo, client_id=self.client_id,
                                 subject_ids=[self.shared])
        content_api.assign_to(self.repo, subject_id=self.shared,
                              login="alla", actor_login="root")
        content_api.publish(self.repo, subject_id=self.shared,
                            actor_login="root")
        self.assertEqual(self.repo.api_client_subject_ids(self.client_id), [])

    def test_public_visibility_report(self):
        report = content_api.public_visibility(self.repo, self.shared)
        self.assertEqual(report["storage"], "shared")
        # Без явных выдач ключу доступно всё общее.
        self.assertEqual([c["name"] for c in report["clients"]], ["Интегратор"])
        self.assertFalse(report["clients"][0]["explicit"])


# ---------- Роутер ----------

class RouterTests(StorageTestBase):
    def test_transfer_requires_admin(self):
        self.assertEqual(
            self.http.get("/admin/content").status_code, 401)
        self.assertEqual(
            self.http.post(f"/admin/content/{self.personal}/publish",
                           headers=self._h("alla", "teacher")).status_code, 403)

    def test_admin_flow(self):
        h = self._h("root", "admin")
        overview = self.http.get("/admin/content", headers=h).json()
        self.assertEqual(overview["shared_count"], 1)
        self.assertEqual(overview["personal_count"], 1)

        moved = self.http.post(f"/admin/content/{self.personal}/publish",
                               headers=h).json()
        self.assertEqual(moved["to"], "shared")
        self.assertEqual(
            self.http.get("/admin/content", headers=h).json()["shared_count"], 2)

        back = self.http.post(f"/admin/content/{self.personal}/assign",
                              json={"login": "boris"}, headers=h).json()
        self.assertEqual((back["to"], back["owner"]), ("personal", "boris"))

    def test_mine_is_per_caller(self):
        r = self.http.get("/subjects/mine", headers=self._h("alla", "teacher"))
        self.assertEqual([s["id"] for s in r.json()["subjects"]],
                         [self.personal])
        r = self.http.get("/subjects/mine", headers=self._h("boris", "teacher"))
        self.assertEqual(r.json()["subjects"], [])
        self.assertEqual(self.http.get("/subjects/mine").status_code, 401)

    def test_bad_transfer_is_400(self):
        h = self._h("root", "admin")
        self.assertEqual(
            self.http.post(f"/admin/content/{self.shared}/publish",
                           headers=h).status_code, 400)
        self.assertEqual(
            self.http.post(f"/admin/content/{self.shared}/assign",
                           json={"login": "stud"}, headers=h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
