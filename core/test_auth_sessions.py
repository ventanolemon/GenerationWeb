"""
Заверенная идентичность: выдача, проверка и отзыв сессий.

Проверяется не только «работает», но и то, ради чего это писалось:
роль берётся из БД в момент запроса, а не из токена и не из заголовка.
Контекст — organizations_readiness.md.

Запуск:
    python -m unittest core.test_auth_sessions
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

from core import auth_sessions  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import auth as auth_router  # noqa: E402


class AuthSessionBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "rootpass", "Админ", "", role="admin")
        self.repo.create_user("alla", "allapass", "Алла", "", role="teacher")
        self.repo.create_user("stud", "studpass", "Студент", "", role="student")

        app = FastAPI()
        errors.install(app)
        app.include_router(auth_router.router)
        app.state.repo = self.repo
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.environ.pop("GEN_TRUST_IDENTITY_HEADERS", None)

    def _login(self, login, password):
        r = self.client.post("/auth/login",
                             json={"login": login, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    @staticmethod
    def _bearer(token):
        return {"Authorization": f"Bearer {token}"}


# ---------- Выдача и проверка ----------

class IssueAndResolveTests(AuthSessionBase):
    def test_login_issues_a_token_and_keeps_the_profile_fields(self):
        body = self.client.post("/auth/login",
                                json={"login": "alla",
                                      "password": "allapass"}).json()
        self.assertTrue(body["token"].startswith("gws_"))
        # Прежние поля никуда не делись — переход не ломает клиентов.
        self.assertEqual(body["login"], "alla")
        self.assertEqual(body["role"], "teacher")

    def test_wrong_password_issues_nothing(self):
        r = self.client.post("/auth/login",
                             json={"login": "alla", "password": "не тот"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("token", r.json())

    def test_token_is_stored_hashed_only(self):
        token = self._login("alla", "allapass")
        rows = self.repo.list_auth_sessions("alla")
        self.assertEqual(len(rows), 1)
        # В базе — хэш, не сам токен: утечка БД не должна давать вход.
        self.assertNotEqual(rows[0]["token_hash"], token)
        self.assertEqual(rows[0]["token_hash"], auth_sessions.hash_token(token))

    def test_me_reports_identity_from_the_server(self):
        token = self._login("alla", "allapass")
        body = self.client.get("/auth/me", headers=self._bearer(token)).json()
        self.assertEqual(body["login"], "alla")
        self.assertEqual(body["role"], "teacher")
        self.assertTrue(body["verified"])
        self.assertEqual(body["source"], "session")

    def test_garbage_token_is_refused(self):
        r = self.client.get("/auth/me", headers=self._bearer("gws_garbage"))
        self.assertEqual(r.status_code, 401)

    def test_no_identity_at_all_is_401(self):
        self.assertEqual(self.client.get("/auth/me").status_code, 401)


# ---------- Главное: роль из БД, а не из токена ----------

class RoleIsReadFromTheDatabaseTests(AuthSessionBase):
    def test_role_change_takes_effect_on_the_existing_session(self):
        """
        Ради этого роль и не хранится в сессии.

        Понизили преподавателя — его уже выданный токен обязан отдавать
        новую роль немедленно, а не после истечения сессии.
        """
        token = self._login("alla", "allapass")
        self.assertEqual(
            self.client.get("/auth/me", headers=self._bearer(token))
            .json()["role"], "teacher")

        self.repo.set_user_role("alla", "student")

        self.assertEqual(
            self.client.get("/auth/me", headers=self._bearer(token))
            .json()["role"], "student")

    def test_token_holder_cannot_claim_a_higher_role_by_header(self):
        """Токен главнее заголовка — иначе дописать себе роль тривиально."""
        token = self._login("stud", "studpass")
        body = self.client.get(
            "/auth/me",
            headers={**self._bearer(token), "X-User-Id": "stud",
                     "X-User-Role": "admin"}).json()
        self.assertEqual(body["role"], "student")


# ---------- Отзыв ----------

class RevocationTests(AuthSessionBase):
    def test_logout_kills_the_session(self):
        token = self._login("alla", "allapass")
        self.client.post("/auth/logout", headers=self._bearer(token))
        self.assertEqual(
            self.client.get("/auth/me", headers=self._bearer(token))
            .status_code, 401)

    def test_logout_is_idempotent(self):
        token = self._login("alla", "allapass")
        self.client.post("/auth/logout", headers=self._bearer(token))
        again = self.client.post("/auth/logout", headers=self._bearer(token))
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["revoked"])

    def test_password_change_revokes_every_session(self):
        first = self._login("alla", "allapass")
        second = self._login("alla", "allapass")
        body = self.client.post("/auth/change-password",
                                json={"login": "alla",
                                      "current_password": "allapass",
                                      "new_password": "новыйпароль"}).json()
        self.assertEqual(body["sessions_revoked"], 2)
        for token in (first, second):
            self.assertEqual(
                self.client.get("/auth/me", headers=self._bearer(token))
                .status_code, 401)

    def test_expired_session_is_refused(self):
        session = auth_sessions.issue(self.repo, "alla", ttl=-1)
        self.assertEqual(
            self.client.get("/auth/me",
                            headers=self._bearer(session["token"]))
            .status_code, 401)

    def test_refusals_do_not_distinguish_missing_from_revoked(self):
        # Иначе перебором отличают несуществующий токен от погашенного.
        token = self._login("alla", "allapass")
        self.client.post("/auth/logout", headers=self._bearer(token))
        revoked = self.client.get("/auth/me", headers=self._bearer(token))
        never = self.client.get("/auth/me",
                                headers=self._bearer("gws_never-existed"))
        self.assertEqual(revoked.status_code, never.status_code)
        self.assertEqual(revoked.json()["detail"], never.json()["detail"])


# ---------- Профиль ----------

class ProfileAuthorizationTests(AuthSessionBase):
    _BODY = {"fio": "Переписано", "group": "", "email": "",
             "about": "", "avatar_color": ""}

    def test_stranger_cannot_rewrite_a_profile(self):
        """
        Дыра, найденная замером: PATCH без единого заголовка переписывал
        ФИО администратора.
        """
        r = self.client.patch("/auth/profile/root", json=self._BODY)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.repo.get_user_profile("root").fio, "Админ")

    def test_logged_in_stranger_still_cannot(self):
        token = self._login("stud", "studpass")
        r = self.client.patch("/auth/profile/root", json=self._BODY,
                              headers=self._bearer(token))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.repo.get_user_profile("root").fio, "Админ")

    def test_owner_can(self):
        token = self._login("stud", "studpass")
        r = self.client.patch("/auth/profile/stud", json=self._BODY,
                              headers=self._bearer(token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.repo.get_user_profile("stud").fio, "Переписано")

    def test_admin_can(self):
        token = self._login("root", "rootpass")
        r = self.client.patch("/auth/profile/stud", json=self._BODY,
                              headers=self._bearer(token))
        self.assertEqual(r.status_code, 200)


# ---------- Переходный режим ----------

class TransitionalHeaderTrustTests(AuthSessionBase):
    def test_headers_are_accepted_while_the_flag_is_on(self):
        os.environ["GEN_TRUST_IDENTITY_HEADERS"] = "1"
        body = self.client.get("/auth/me",
                               headers={"X-User-Id": "alla",
                                        "X-User-Role": "teacher"}).json()
        self.assertEqual(body["login"], "alla")
        # Личность заявлена, а не заверена, и это видно.
        self.assertFalse(body["verified"])
        self.assertEqual(body["source"], "header")

    def test_headers_stop_meaning_anything_when_the_flag_is_off(self):
        os.environ["GEN_TRUST_IDENTITY_HEADERS"] = "0"
        r = self.client.get("/auth/me", headers={"X-User-Id": "alla",
                                                 "X-User-Role": "admin"})
        self.assertEqual(r.status_code, 401)

    def test_tokens_keep_working_when_the_flag_is_off(self):
        token = self._login("alla", "allapass")
        os.environ["GEN_TRUST_IDENTITY_HEADERS"] = "0"
        body = self.client.get("/auth/me", headers=self._bearer(token)).json()
        self.assertEqual(body["login"], "alla")
        self.assertTrue(body["verified"])

    def test_missing_role_header_defaults_to_the_strictest_role(self):
        # То же правило, что чинилось в sync.py: «не доехал» не означает
        # «можно больше».
        os.environ["GEN_TRUST_IDENTITY_HEADERS"] = "1"
        body = self.client.get("/auth/me",
                               headers={"X-User-Id": "alla"}).json()
        self.assertEqual(body["role"], "student")

    def test_bad_token_is_not_silently_downgraded_to_headers(self):
        """
        Протухшая сессия не должна давать больше прав, чем свежая: откат к
        заголовкам при негодном токене означал бы ровно это.
        """
        os.environ["GEN_TRUST_IDENTITY_HEADERS"] = "1"
        r = self.client.get("/auth/me",
                            headers={**self._bearer("gws_stale"),
                                     "X-User-Id": "root",
                                     "X-User-Role": "admin"})
        self.assertEqual(r.status_code, 401)


# ---------- Разбор заголовка ----------

class BearerParsingTests(unittest.TestCase):
    def test_parses_scheme_case_insensitively(self):
        self.assertEqual(auth_sessions.bearer_token("Bearer abc"), "abc")
        self.assertEqual(auth_sessions.bearer_token("bearer abc"), "abc")
        self.assertEqual(auth_sessions.bearer_token("BEARER  abc  "), "abc")

    def test_other_schemes_and_junk_give_nothing(self):
        for value in (None, "", "   ", "Basic abc", "abc", "Bearer"):
            self.assertEqual(auth_sessions.bearer_token(value), "")


if __name__ == "__main__":
    unittest.main()
