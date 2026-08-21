"""
Режим разработчика: примерка роли.

Из плана (§12) требовались три вещи, и каждая проверяется здесь отдельно,
потому что нарушение каждой ломает своё:

  1. понижать себе роль вправе ТОЛЬКО аккаунт с флагом разработчика;
  2. примерка обязана быть ВИДИМОЙ — иначе разработчик забудет и примет
     чужую картину за свою;
  3. примерка НЕ пишет попытки от имени примеряемого — иначе аналитика
     курса портится отладочными прохождениями.

Четвёртое не требовалось, но следует из устройства и проверяется тоже:
примерка идёт только ВНИЗ. Благодаря этому забытая проверка роли где-то в
коде даёт не дыру, а несовпадение картинки.

Запуск:
    python -m unittest core.test_role_tryon
"""

from __future__ import annotations

import unittest

from core.attempts import attempts_from_session
from core.auth_sessions import (
    ROLE_ORDER, AuthError, Identity, try_on_role,
)
from core.scenarios import Scenario, SessionMode
from core.tmpdb import temp_path  # noqa: E402


def _dev(role: str = "admin") -> Identity:
    return Identity(login="dev", role=role, is_superuser=True)


class WhoMayTryOn(unittest.TestCase):

    def test_only_the_developer_may(self):
        for who in (Identity(login="t", role="teacher"),
                    Identity(login="a", role="admin"),
                    Identity(login="s", role="student")):
            with self.subTest(role=who.role):
                with self.assertRaises(AuthError) as ctx:
                    try_on_role(who, "student")
                self.assertEqual(ctx.exception.status, 403)

    def test_admin_of_an_organization_is_not_a_developer(self):
        # Разные оси (§8.2): `admin` — админ СВОЕЙ организации, примерка —
        # инструмент того, кто продукт делает.
        with self.assertRaises(AuthError):
            try_on_role(Identity(login="orgadmin", role="admin"), "student")

    def test_empty_request_changes_nothing(self):
        who = _dev()
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIs(try_on_role(who, value), who)


class WhatMayBeTriedOn(unittest.TestCase):

    def test_only_down_never_up(self):
        """
        Примерка вверх дала бы повышение — то есть перестала бы быть
        примеркой. На этом же свойстве держится безопасность всей затеи:
        забытая проверка роли где-то в коде показывает не ту картинку, но
        не открывает лишнего.
        """
        with self.assertRaises(AuthError) as ctx:
            try_on_role(_dev(role="teacher"), "admin")
        self.assertEqual(ctx.exception.status, 403)

    def test_unknown_role_is_refused(self):
        with self.assertRaises(AuthError) as ctx:
            try_on_role(_dev(), "wizard")
        self.assertEqual(ctx.exception.status, 400)

    def test_superuser_flag_is_dropped(self):
        # Иначе «примерил студента» показывает студента, который при этом
        # управляет развёртыванием, — то есть не показывает студента.
        self.assertFalse(try_on_role(_dev(), "student").is_superuser)

    def test_every_role_of_the_vocabulary_can_be_tried_on(self):
        for role in ROLE_ORDER:
            with self.subTest(role=role):
                self.assertEqual(try_on_role(_dev(), role).role, role)


class WhoYouRemain(unittest.TestCase):

    def test_login_never_changes(self):
        """
        Главное свойство примерки: это другой ВЗГЛЯД, а не другой человек.
        Подмена логина дала бы возможность действовать от чужого имени —
        это уже не отладка, и всё записанное вело бы не туда.
        """
        self.assertEqual(try_on_role(_dev(), "student").login, "dev")

    def test_the_true_role_is_remembered(self):
        who = try_on_role(_dev(role="admin"), "student")
        self.assertEqual(who.true_role, "admin")
        self.assertTrue(who.trying_on)

    def test_no_tryon_means_no_true_role(self):
        # Признак должен различать «примерки нет» и «примеряю свою же
        # роль»: интерфейс по нему решает, показывать ли предупреждение.
        self.assertFalse(_dev().trying_on)
        self.assertTrue(try_on_role(_dev(), "admin").trying_on)

    def test_organization_is_kept(self):
        who = try_on_role(
            Identity(login="dev", role="admin", is_superuser=True,
                     organization_id=7), "student")
        self.assertEqual(who.organization_id, 7)


class _Outcome:
    def __init__(self, index: int):
        self.index = index
        self.accepted = True
        self.mode = "soft"
        self.attempts = 1
        self.reason = "ok"


class _Session:
    outcomes = [_Outcome(0), _Outcome(1)]


class AttemptsDuringTryOn(unittest.TestCase):
    """Третье требование плана: примерка не портит статистику курса."""

    def _records(self, trying_on: bool):
        scenario = Scenario.for_mode(SessionMode.HOMEWORK)
        return attempts_from_session(
            _Session(), scenario,
            session_id="s1", user_id="dev", partition_id=201,
            trying_on=trying_on)

    def test_attempt_is_still_written(self):
        # Не писать вовсе было бы неверно: разработчик действительно
        # отвечал, и ход обязан остаться в журнале под его логином.
        self.assertEqual(len(self._records(True)), 2)

    def test_attempt_does_not_count_toward_stats(self):
        for record in self._records(True):
            self.assertFalse(record.counts_toward_stats)

    def test_without_tryon_the_contract_is_untouched(self):
        for record in self._records(False):
            self.assertTrue(record.counts_toward_stats)

    def test_tryon_can_only_remove_the_count_never_add_it(self):
        """
        Свободная тренировка не пишет попыток вовсе; примерка не должна
        превращаться в способ что-то записать там, где режим этого не
        предполагает.
        """
        free = Scenario.for_mode(SessionMode.PRACTICE_FREE)
        self.assertEqual(
            attempts_from_session(_Session(), free, session_id="s1",
                                  user_id="dev", partition_id=201,
                                  trying_on=True),
            [])


class OverHttpTests(unittest.TestCase):
    """
    Примерка по проводу: заголовок `X-Acting-Role`.

    Проверяется именно HTTP-путь, а не только правило: заголовок надо было
    протянуть через резолвер, четыре зависимости и гейты, и «протянул
    везде» — утверждение о коде, которое дешевле проверить, чем
    перечитать.
    """

    def setUp(self):
        import os
        import tempfile
        from core.repository import Repository
        self.db = temp_path(suffix=".db")
        self.repo = Repository(self.db)
        self.repo.create_user("dev", "p", "Разработчик", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.set_superuser("dev", True)

    def tearDown(self):
        import os
        if os.path.exists(self.db):
            os.unlink(self.db)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import auth as auth_router
        app = FastAPI()
        app.include_router(auth_router.router)
        app.state.repo = self.repo
        return TestClient(app)

    def _headers(self, login: str, acting: str = "") -> dict:
        from core import auth_sessions as A
        token = A.issue(self.repo, login)["token"]
        head = {"Authorization": f"Bearer {token}"}
        if acting:
            head["X-Acting-Role"] = acting
        return head

    def test_me_reports_the_tryon(self):
        # Второе требование плана: примерка обязана быть ВИДИМОЙ, и
        # видимость идёт с сервера, а не из памяти клиента.
        body = self._client().get(
            "/auth/me", headers=self._headers("dev", "student")).json()
        self.assertEqual(body["role"], "student")
        self.assertEqual(body["true_role"], "admin")
        self.assertTrue(body["trying_on"])
        self.assertEqual(body["login"], "dev")

    def test_me_without_the_header_is_untouched(self):
        body = self._client().get(
            "/auth/me", headers=self._headers("dev")).json()
        self.assertEqual(body["role"], "admin")
        self.assertIsNone(body["true_role"])
        self.assertFalse(body["trying_on"])

    def test_right_to_try_on_comes_from_the_database(self):
        # Иначе интерфейс либо прячет кнопку у того, кому она положена,
        # либо показывает её тому, кто получит 403.
        dev = self._client().get("/auth/me", headers=self._headers("dev"))
        alla = self._client().get("/auth/me", headers=self._headers("alla"))
        self.assertTrue(dev.json()["can_try_on"])
        self.assertFalse(alla.json()["can_try_on"])

    def test_header_from_a_non_developer_is_refused(self):
        r = self._client().get(
            "/auth/me", headers=self._headers("alla", "student"))
        self.assertEqual(r.status_code, 403)

    def test_unknown_role_in_the_header_is_refused(self):
        r = self._client().get(
            "/auth/me", headers=self._headers("dev", "wizard"))
        self.assertEqual(r.status_code, 400)

    def test_leaving_the_tryon_is_just_dropping_the_header(self):
        """
        Примерка живёт в ЗАПРОСЕ, а не в сессии. Из неё нельзя застрять:
        забытая на сервере примерка была бы худшим видом невидимости —
        разработчик закрыл вкладку, а продукт продолжает показывать ему
        чужую картину.
        """
        client = self._client()
        token = self._headers("dev")["Authorization"]
        trying = client.get("/auth/me", headers={
            "Authorization": token, "X-Acting-Role": "student"}).json()
        back = client.get("/auth/me",
                          headers={"Authorization": token}).json()
        self.assertTrue(trying["trying_on"])
        self.assertFalse(back["trying_on"])


if __name__ == "__main__":
    unittest.main()
