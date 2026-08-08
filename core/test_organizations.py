"""
Организации: контейнер, границы и два администратора (§8 плана).

Проверяется не «поля сохраняются», а то, ради чего §8 затевался:
чужой организации не видно вовсе, встроенные предметы — единственное,
что пересекает границу, и `admin` больше не значит «может всё в
развёртывании».

Запуск:
    python -m unittest core.test_organizations
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import content_authz, organizations_api  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import organizations as orgs_router  # noqa: E402
from generator_service.routers import packages as packages_router  # noqa: E402


class OrgTestBase(unittest.TestCase):
    """
    Две организации: «Физфак» (id 1, из миграции) и «Химфак».

    root  — superuser, админ Физфака (так его настроила миграция + bootstrap)
    alla  — teacher Физфака
    boris — admin Химфака, БЕЗ флага развёртывания
    clara — teacher Химфака
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)

        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        organizations_api.ensure_bootstrapped(self.repo)
        self.phys = self.repo.default_organization_id()
        self.repo.rename_organization(self.phys, "Физфак")

        self.chem = self.repo.create_organization("Химфак")
        self.repo.create_user("boris", "p", "Борис", "", role="admin",
                              organization_id=self.chem)
        self.repo.create_user("clara", "p", "Клара", "", role="teacher",
                              organization_id=self.chem)
        self.repo.set_organization_owner(self.chem, "boris")

        app = FastAPI()
        errors.install(app)
        app.include_router(orgs_router.router)
        app.include_router(packages_router.router)
        app.state.repo = self.repo
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    @staticmethod
    def _h(login, role):
        return {"X-User-Id": login, "X-User-Role": role}

    def _subject(self, name, owner, org_id):
        sid = self.repo.create_subject(name, name)
        self.repo.set_subject_owner(sid, owner)
        self.repo.set_subject_organization(sid, org_id)
        return sid


# ---------- Миграция ----------

class MigrationPreservesBehaviourTests(unittest.TestCase):
    def test_existing_deployment_keeps_working(self):
        """
        Миграция обязана быть поведение-сохраняющей: вчерашний админ должен
        остаться и админом своей организации, и администратором
        развёртывания.
        """
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        try:
            repo = Repository(path)
            repo.create_user("root", "p", "Админ", "", role="admin")
            repo.create_user("alla", "p", "Алла", "", role="teacher")
            organizations_api.ensure_bootstrapped(repo)

            org_id = repo.default_organization_id()
            self.assertIsNotNone(org_id, "организация по умолчанию не заведена")
            # Все существующие — внутри неё.
            self.assertEqual(sorted(repo.organization_members(org_id)),
                             ["alla", "root"])
            self.assertTrue(repo.is_superuser("root"))
            self.assertFalse(repo.is_superuser("alla"))
            self.assertEqual(repo.get_organization(org_id)["owner_login"],
                             "root")
        finally:
            os.unlink(path)

    def test_new_user_lands_in_the_default_organization(self):
        # Иначе зарегистрироваться можно, а пользоваться нельзя.
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        try:
            repo = Repository(path)
            repo.create_user("nova", "p", "Новенький", "")
            self.assertEqual(repo.user_organization_id("nova"),
                             repo.default_organization_id())
        finally:
            os.unlink(path)


# ---------- Две оси администрирования ----------

class TwoKindsOfAdminTests(OrgTestBase):
    def test_org_admin_cannot_install_packages(self):
        """
        Суть §8.1: набор установленных пакетов один на развёртывание, иначе
        решение «какой код здесь исполняется» переходит к организации.
        boris — полноценный админ Химфака, но не администратор развёртывания.
        """
        r = self.client.get("/admin/packages/requests",
                            headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 403)

    def test_superuser_can(self):
        r = self.client.get("/admin/packages/requests",
                            headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200)

    def test_org_admin_cannot_create_organizations(self):
        r = self.client.post("/admin/organizations", json={"name": "Матфак"},
                             headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 403)

    def test_superuser_can_create_organizations(self):
        r = self.client.post("/admin/organizations", json={"name": "Матфак"},
                             headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["name"], "Матфак")

    def test_teacher_is_not_an_org_admin(self):
        r = self.client.get(f"/admin/organizations/{self.chem}",
                            headers=self._h("clara", "teacher"))
        self.assertEqual(r.status_code, 403)


# ---------- Граница контейнера ----------

class BoundaryTests(OrgTestBase):
    def test_foreign_organization_is_404_not_403(self):
        # «Есть, но не для вас» перебором id выдаёт, что существует.
        r = self.client.get(f"/admin/organizations/{self.phys}",
                            headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 404)

    def test_own_organization_is_visible(self):
        r = self.client.get(f"/admin/organizations/{self.chem}",
                            headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(sorted(r.json()["members"]), ["boris", "clara"])

    def test_superuser_sees_any_organization(self):
        r = self.client.get(f"/admin/organizations/{self.chem}",
                            headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200)

    def test_cannot_admit_into_a_foreign_organization(self):
        r = self.client.post(f"/admin/organizations/{self.phys}/members",
                             json={"login": "clara"},
                             headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.repo.user_organization_id("clara"), self.chem)


# ---------- Видимость контента ----------

class ContentScopeTests(OrgTestBase):
    def test_org_admin_does_not_see_foreign_subjects(self):
        mine = self._subject("Химия", "clara", self.chem)
        theirs = self._subject("Физика", "alla", self.phys)

        scope = content_authz.visible_scope(self.repo, "boris", "admin")
        self.assertIn(mine, scope)
        self.assertNotIn(theirs, scope,
                         "предмет чужой организации попал в скоуп админа")

    def test_builtin_subjects_cross_the_boundary(self):
        # Единственное исключение по §8.1: они принадлежат продукту.
        builtin = self._subject("Встроенный", None, None)
        for login in ("boris", "alla"):
            self.assertIn(builtin,
                          content_authz.visible_scope(self.repo, login, "admin"))

    def test_superuser_sees_everything(self):
        mine = self._subject("Химия", "clara", self.chem)
        theirs = self._subject("Физика", "alla", self.phys)
        scope = content_authz.visible_scope(self.repo, "root", "admin")
        self.assertIn(mine, scope)
        self.assertIn(theirs, scope)

    def test_grant_cannot_smuggle_a_subject_across_the_boundary(self):
        """
        Выдачи считаются мимо visible_subject_ids — по таблице
        subject_grants. Через API выдать предмет чужой организации нельзя,
        но граница обязана держаться на том, что нарушение не проходит, а
        не на том, что его негде совершить.
        """
        theirs = self._subject("Физика", "alla", self.phys)
        self.repo.replace_subject_grants("clara", [theirs])
        scope = content_authz.visible_scope(self.repo, "clara", "teacher")
        self.assertNotIn(theirs, scope)


# ---------- Владение организацией (§8.2) ----------

class OwnershipTests(OrgTestBase):
    def test_owner_can_transfer_to_a_member_admin(self):
        self.repo.set_user_role("clara", "admin")
        r = self.client.post(f"/admin/organizations/{self.chem}/owner",
                             json={"login": "clara"},
                             headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.repo.get_organization(self.chem)["owner_login"],
                         "clara")

    def test_cannot_hand_ownership_to_an_outsider(self):
        r = self.client.post(f"/admin/organizations/{self.chem}/owner",
                             json={"login": "alla"},
                             headers=self._h("boris", "admin"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("не состоит в организации", r.json()["detail"])

    def test_a_stranger_cannot_take_ownership(self):
        self.repo.set_user_role("clara", "admin")
        r = self.client.post(f"/admin/organizations/{self.chem}/owner",
                             json={"login": "clara"},
                             headers=self._h("clara", "admin"))
        self.assertEqual(r.status_code, 400)

    def test_superuser_can_reassign_an_abandoned_organization(self):
        """
        §8.2 требует ровно один запасной путь: без него организация с
        потерянным доступом остаётся без владельца навсегда, и «владельца
        нельзя понизить» превращается из гарантии в ловушку.
        """
        self.repo.set_user_role("clara", "admin")
        r = self.client.post(f"/admin/organizations/{self.chem}/owner",
                             json={"login": "clara"},
                             headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200, r.text)

    def test_owner_cannot_be_moved_out_without_transferring(self):
        r = self.client.delete(
            f"/admin/organizations/{self.chem}/members/boris",
            headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("передайте владение", r.json()["detail"])


# ---------- Последний администратор развёртывания ----------

class LastSuperuserTests(OrgTestBase):
    def test_cannot_drop_the_last_one(self):
        r = self.client.post("/admin/superusers/root",
                             json={"is_superuser": False},
                             headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 400)
        self.assertTrue(self.repo.is_superuser("root"))

    def test_can_grant_and_then_revoke(self):
        granted = self.client.post("/admin/superusers/boris",
                                   json={"is_superuser": True},
                                   headers=self._h("root", "admin"))
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertTrue(self.repo.is_superuser("boris"))

        revoked = self.client.post("/admin/superusers/boris",
                                   json={"is_superuser": False},
                                   headers=self._h("root", "admin"))
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(self.repo.is_superuser("boris"))


# ---------- Перевод между организациями ----------

class MoveUserTests(OrgTestBase):
    def test_move_bumps_the_scope_epoch(self):
        """
        Перевод меняет ВЕСЬ видимый набор — ровно то, для чего строился
        scope_version. Без инкремента десктоп жил бы с прежним набором до
        первой правки контента.
        """
        before = self.repo.scope_version("clara")
        self.client.post(f"/admin/organizations/{self.phys}/members",
                         json={"login": "clara"},
                         headers=self._h("root", "admin"))
        self.assertEqual(self.repo.user_organization_id("clara"), self.phys)
        self.assertGreater(self.repo.scope_version("clara"), before)

    def test_expelled_user_has_no_organization(self):
        self.client.delete(f"/admin/organizations/{self.chem}/members/clara",
                           headers=self._h("boris", "admin"))
        self.assertIsNone(self.repo.user_organization_id("clara"))


# ---------- Своя организация ----------

class MineTests(OrgTestBase):
    def test_reports_membership_and_ownership(self):
        body = self.client.get("/organizations/mine",
                               headers=self._h("boris", "admin")).json()
        self.assertEqual(body["organization"]["name"], "Химфак")
        self.assertTrue(body["is_owner"])
        self.assertFalse(body["is_superuser"])

    def test_teacher_sees_their_organization_too(self):
        body = self.client.get("/organizations/mine",
                               headers=self._h("clara", "teacher")).json()
        self.assertEqual(body["organization"]["name"], "Химфак")
        self.assertFalse(body["is_owner"])


# ---------- Умолчание видимости — настройка организации ----------

class DefaultAccessTests(OrgTestBase):
    def test_setting_is_per_organization(self):
        self.repo.set_organization_default_access(self.chem, "none")
        self.assertEqual(self.repo.effective_default_access("clara"), "none")
        # У соседней организации всё по-прежнему.
        self.assertEqual(self.repo.effective_default_access("alla"), "all")


if __name__ == "__main__":
    unittest.main()
