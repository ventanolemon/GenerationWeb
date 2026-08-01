"""
Публичный API v1: ключи приложений, скоуп, квоты, публичные идентификаторы
(этапы 1–3 из docs/architecture/public_api.md).

Что здесь важно проверить, помимо «работает»:

  * ключ хранится хэшем и открытым не восстанавливается;
  * отказ не различает «нет такого ключа» и «ключ отозван» — иначе перебор
    получил бы оракула;
  * «темы нет» и «тема не для этого ключа» отвечают ОДИНАКОВО по той же
    причине;
  * наружу не уходит ни `partition_id`, ни число `constracted` — ни в теле,
    ни в `meta`;
  * скоуп по умолчанию — только встроенные предметы: авторский контент
    преподавателей наружу без явного решения не отдаётся;
  * квота считается до работы и режет на 429.

Запуск: python -m unittest core.test_public_api -v  (из корня монорепо)
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

from core import api_clients, public_api  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.task import StaticTask  # noqa: E402
from exercises.english.generators import WordsSession  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import admin_clients as admin_router  # noqa: E402
from generator_service.routers import public_v1  # noqa: E402
from generator_service.session_store import SessionStore  # noqa: E402


class _StaticGen:
    name = "static"

    def generate(self):
        return StaticTask([TextBlock("2+2?")], [TextBlock("4")],
                          {"partition_id": 999, "seed": 7})


class _InteractiveGen:
    name = "words"

    def generate(self):
        return WordsSession({"cat": "кот", "dog": "собака"})


class _FakeRegistry:
    """Реестр, где статическая тема — одна партиция, интерактивная — другая."""

    def __init__(self, static_id, interactive_id):
        self._gens = {static_id: _StaticGen(), interactive_id: _InteractiveGen()}

    def has(self, pid):
        return pid in self._gens

    def get(self, pid, params=None):
        return self._gens[pid]


class PublicApiTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")

        # Встроенный предмет (owner NULL) и авторский (owner = преподаватель).
        self.builtin = self.repo.ensure_subject(3, "Физика")
        self.authored = self.repo.create_subject("Курс Аллы", "Курс Аллы",
                                                 owner_user_id="alla")
        self.static_pid = self.repo.upsert_partition(
            self.builtin, "Сила F=ma", 0, {})
        self.words_pid = self.repo.upsert_partition(
            self.builtin, "Слова", 4, {})
        self.authored_pid = self.repo.upsert_partition(
            self.authored, "Раздел Аллы", 0, {})

        self.client_id = self.repo.create_api_client("Интегратор", "root", 1000)
        self.key = api_clients.issue_key(
            self.repo, client_id=self.client_id)["key"]

        app = FastAPI()
        errors.install(app)
        app.include_router(public_v1.router)
        app.include_router(admin_router.router)
        app.state.repo = self.repo
        app.state.registry = _FakeRegistry(self.static_pid, self.words_pid)
        app.state.sessions = SessionStore(repo=self.repo,
                                          task_factory=lambda p, u: None)
        self.app = app
        self.http = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.unlink(self.db_path)

    def _bearer(self, key=None):
        return {"Authorization": f"Bearer {key or self.key}"}

    @staticmethod
    def _admin():
        return {"X-User-Id": "root", "X-User-Role": "admin"}

    def _topic_id(self, partition_id):
        return self.repo.public_id("partition", partition_id)


# ---------- Ключи ----------

class KeyTests(PublicApiTestBase):
    def test_key_is_stored_hashed_only(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key_hash, prefix FROM api_keys").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(self.key, [r[0] for r in rows])
        self.assertEqual(rows[0][0], api_clients.hash_key(self.key))
        self.assertTrue(self.key.startswith(rows[0][1]))

    def test_authenticate_accepts_valid_key(self):
        client = api_clients.authenticate(self.repo, self.key)
        self.assertEqual(client["client_id"], self.client_id)

    def test_unknown_and_revoked_are_indistinguishable(self):
        api_clients.revoke_key(self.repo, client_id=self.client_id,
                               prefix=self.key[:self.key.rindex("_") + 9])
        messages = set()
        for bad in (self.key, "gw_live_совсем-не-ключ"):
            with self.assertRaises(api_clients.ApiAuthError) as ctx:
                api_clients.authenticate(self.repo, bad)
            messages.add(str(ctx.exception))
        self.assertEqual(len(messages), 1, "отказ обязан быть одинаковым")

    def test_suspended_client_is_403_not_401(self):
        api_clients.set_status(self.repo, client_id=self.client_id,
                               status="suspended")
        with self.assertRaises(api_clients.ApiAuthError) as ctx:
            api_clients.authenticate(self.repo, self.key)
        self.assertEqual(ctx.exception.status, 403)

    def test_browser_key_requires_origins(self):
        with self.assertRaisesRegex(api_clients.ApiClientError, "origin"):
            api_clients.issue_key(self.repo, client_id=self.client_id,
                                  kind="browser")

    def test_browser_key_is_bound_to_origin(self):
        key = api_clients.issue_key(
            self.repo, client_id=self.client_id, kind="browser",
            allowed_origins="https://ok.example, https://also.example")["key"]
        self.assertTrue(api_clients.authenticate(
            self.repo, key, origin="https://ok.example"))
        for bad in ("https://evil.example", None, ""):
            with self.assertRaises(api_clients.ApiAuthError) as ctx:
                api_clients.authenticate(self.repo, key, origin=bad)
            self.assertEqual(ctx.exception.status, 403)

    def test_server_key_ignores_origin(self):
        self.assertTrue(api_clients.authenticate(
            self.repo, self.key, origin="https://anything.example"))


# ---------- Скоуп ----------

class ScopeTests(PublicApiTestBase):
    def test_default_scope_is_builtin_only(self):
        ids = api_clients.client_subject_ids(self.repo, self.client_id)
        self.assertIn(self.builtin, ids)
        self.assertNotIn(self.authored, ids,
                         "авторский контент наружу без решения не уходит")

    def test_explicit_grants_replace_the_default(self):
        api_clients.set_subjects(self.repo, client_id=self.client_id,
                                 subject_ids=[self.authored])
        ids = api_clients.client_subject_ids(self.repo, self.client_id)
        self.assertEqual(ids, [self.authored])

    def test_unknown_subject_rejected(self):
        with self.assertRaisesRegex(api_clients.ApiClientError, "9999"):
            api_clients.set_subjects(self.repo, client_id=self.client_id,
                                     subject_ids=[9999])


# ---------- Квота ----------

class QuotaTests(PublicApiTestBase):
    def _client(self):
        return api_clients.authenticate(self.repo, self.key)

    def test_counts_up_and_cuts_off(self):
        api_clients.set_quota(self.repo, client_id=self.client_id,
                              daily_quota=2)
        client = self._client()
        api_clients.check_and_count(self.repo, client)
        api_clients.check_and_count(self.repo, client)
        with self.assertRaises(api_clients.ApiAuthError) as ctx:
            api_clients.check_and_count(self.repo, client)
        self.assertEqual(ctx.exception.status, 429)

    def test_zero_quota_means_unlimited(self):
        api_clients.set_quota(self.repo, client_id=self.client_id,
                              daily_quota=0)
        client = self._client()
        for _ in range(5):
            api_clients.check_and_count(self.repo, client)

    def test_usage_snapshot_matches(self):
        client = self._client()
        api_clients.check_and_count(self.repo, client)
        self.assertEqual(
            api_clients.usage_snapshot(self.repo, client)["used"], 1)


# ---------- Публичные идентификаторы и каталог ----------

class PublicIdTests(PublicApiTestBase):
    def test_public_ids_are_stable_and_unique(self):
        first = self.repo.public_id("subject", self.builtin)
        self.assertEqual(first, self.repo.public_id("subject", self.builtin))
        self.assertNotEqual(first, self.repo.public_id("partition",
                                                       self.static_pid))
        self.assertNotEqual(str(self.builtin), first, "не внутренний id")

    def test_public_id_resolves_back(self):
        pid = self.repo.public_id("partition", self.static_pid)
        self.assertEqual(self.repo.resolve_public_id("partition", pid),
                         self.static_pid)

    def test_deleted_partition_does_not_resolve(self):
        pid = self.repo.public_id("partition", self.static_pid)
        self.repo.delete_partition(self.static_pid)
        self.assertIsNone(self.repo.resolve_public_id("partition", pid))

    def test_migration_backfills_rows_that_predate_it(self):
        """Апгрейд боевой БД: строки, лежавшие там до миграции, получают id."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        try:
            with sqlite3.connect(path) as conn:
                conn.executescript(
                    "CREATE TABLE Subjects ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  subject_name TEXT NOT NULL DEFAULT '',"
                    "  pra_subject TEXT NOT NULL DEFAULT '');"
                )
                conn.executemany(
                    "INSERT INTO Subjects (subject_name, pra_subject) "
                    "VALUES (?, ?)",
                    [("Физика", "Физика"), ("Английский", "Английский")])
                conn.commit()
            Repository(path)            # прогоняет миграции, включая 008
            with sqlite3.connect(path) as conn:
                ids = [r[0] for r in conn.execute(
                    "SELECT public_id FROM Subjects").fetchall()]
            self.assertEqual(len(ids), 2)
            self.assertTrue(all(ids), "все существовавшие строки получили id")
            self.assertEqual(len(set(ids)), 2, "id уникальны")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_rows_created_after_migration_get_id_lazily(self):
        # Пути вставки (bootstrap, sync, CRUD) поля не знают — оно
        # проставляется при первом обращении публичного API.
        new_pid = self.repo.upsert_partition(self.builtin, "Новый", 0, {})
        with sqlite3.connect(self.db_path) as conn:
            before = conn.execute(
                "SELECT public_id FROM Partitions WHERE id = ?",
                (new_pid,)).fetchone()[0]
        self.assertIsNone(before)
        assigned = self.repo.public_id("partition", new_pid)
        self.assertTrue(assigned)
        self.assertEqual(self.repo.public_id("partition", new_pid), assigned)


class CatalogTests(PublicApiTestBase):
    def test_catalog_hides_internal_identifiers(self):
        body = public_api.catalog(self.repo, self.client_id)
        subject = body["subjects"][0]
        self.assertEqual(set(subject), {"id", "name", "topics"})
        topic = subject["topics"][0]
        self.assertEqual(set(topic), {"id", "name", "kind"})
        self.assertNotIn("constracted", topic)
        self.assertNotIn("partition_id", topic)

    def test_kind_is_a_word_not_a_number(self):
        body = public_api.catalog(self.repo, self.client_id)
        kinds = {t["kind"] for s in body["subjects"] for t in s["topics"]}
        self.assertTrue(kinds <= set(public_api.KIND_BY_CONSTRACTED.values()))
        self.assertIn("graph", kinds)          # words_pid заведён с constracted=4

    def test_catalog_respects_scope(self):
        names = {s["name"] for s in
                 public_api.catalog(self.repo, self.client_id)["subjects"]}
        self.assertIn("Физика", names)
        self.assertNotIn("Курс Аллы", names)

    def test_catalog_skips_topics_without_generator(self):
        registry = self.app.state.registry
        body = public_api.catalog(self.repo, self.client_id, registry=registry)
        topics = {t["name"] for s in body["subjects"] for t in s["topics"]}
        self.assertEqual(topics, {"Сила F=ma", "Слова"})

    def test_resolve_topic_hides_existence_of_foreign_topics(self):
        foreign = self.repo.public_id("partition", self.authored_pid)
        with self.assertRaises(public_api.PublicApiError) as out_of_scope:
            public_api.resolve_topic(self.repo, self.client_id, foreign)
        with self.assertRaises(public_api.PublicApiError) as nonexistent:
            public_api.resolve_topic(self.repo, self.client_id, "нет-такого")
        self.assertEqual(str(out_of_scope.exception).replace(foreign, "X"),
                         str(nonexistent.exception).replace("нет-такого", "X"))


# ---------- HTTP ----------

class PublicRouterTests(PublicApiTestBase):
    def test_requires_bearer_key(self):
        r = self.http.get("/v1/catalog")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "unauthenticated")

    def test_me_reports_quota_without_spending_it(self):
        body = self.http.get("/v1/me", headers=self._bearer()).json()
        self.assertEqual(body["client"], "Интегратор")
        self.assertEqual(body["usage"]["used"], 0)
        self.http.get("/v1/catalog", headers=self._bearer())
        self.assertEqual(
            self.http.get("/v1/me", headers=self._bearer()).json()["usage"]["used"],
            0, "каталог и /me квоту не тратят")

    def test_generate_static_task(self):
        topic = self._topic_id(self.static_pid)
        r = self.http.post("/v1/tasks", json={"topic_id": topic},
                           headers=self._bearer())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["type"], "static")
        self.assertEqual(body["topic_id"], topic)
        self.assertTrue(body["statement"])
        # Внутренний id не должен уехать даже через meta.
        self.assertNotIn("partition_id", body["meta"])
        self.assertEqual(body["meta"]["seed"], 7)

    def test_generation_spends_quota(self):
        api_clients.set_quota(self.repo, client_id=self.client_id,
                              daily_quota=1)
        topic = self._topic_id(self.static_pid)
        self.assertEqual(
            self.http.post("/v1/tasks", json={"topic_id": topic},
                           headers=self._bearer()).status_code, 200)
        r = self.http.post("/v1/tasks", json={"topic_id": topic},
                           headers=self._bearer())
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"]["code"], "rate_limited")

    def test_foreign_topic_is_404(self):
        foreign = self._topic_id(self.authored_pid)
        r = self.http.post("/v1/tasks", json={"topic_id": foreign},
                           headers=self._bearer())
        self.assertEqual(r.status_code, 404)

    def test_interactive_flow(self):
        topic = self._topic_id(self.words_pid)
        started = self.http.post("/v1/tasks", json={"topic_id": topic},
                                 headers=self._bearer()).json()
        self.assertEqual(started["type"], "interactive")
        self.assertTrue(started["session_id"])
        self.assertTrue(started["prompt"])

        r = self.http.post(f"/v1/tasks/{started['session_id']}/answer",
                           json={"answer": "cat"}, headers=self._bearer())
        self.assertEqual(r.status_code, 200)
        turn = r.json()
        self.assertEqual(set(turn), {"type", "session_id", "correct",
                                     "feedback", "next_prompt", "is_finished"})

    def test_answer_to_unknown_session_is_404(self):
        r = self.http.post("/v1/tasks/нет-такой/answer",
                           json={"answer": "x"}, headers=self._bearer())
        self.assertEqual(r.status_code, 404)

    def test_suspended_client_is_refused(self):
        api_clients.set_status(self.repo, client_id=self.client_id,
                               status="suspended")
        r = self.http.get("/v1/catalog", headers=self._bearer())
        self.assertEqual(r.status_code, 403)


class AdminClientsRouterTests(PublicApiTestBase):
    def test_requires_admin(self):
        self.assertEqual(self.http.get("/admin/api-clients").status_code, 401)
        self.assertEqual(
            self.http.get("/admin/api-clients",
                          headers={"X-User-Id": "alla",
                                   "X-User-Role": "teacher"}).status_code, 403)

    def test_full_lifecycle(self):
        h = self._admin()
        created = self.http.post("/admin/api-clients",
                                 json={"name": "Партнёр", "daily_quota": 50},
                                 headers=h).json()
        cid = created["id"]
        self.assertEqual(created["daily_quota"], 50)

        issued = self.http.post(f"/admin/api-clients/{cid}/keys",
                                json={"kind": "server"}, headers=h).json()
        self.assertTrue(issued["key"].startswith("gw_live_"))

        # Ключ работает…
        self.assertEqual(
            self.http.get("/v1/me",
                          headers=self._bearer(issued["key"])).status_code, 200)
        # …пока не отозван.
        self.assertEqual(
            self.http.delete(
                f"/admin/api-clients/{cid}/keys/{issued['prefix']}",
                headers=h).status_code, 200)
        self.assertEqual(
            self.http.get("/v1/me",
                          headers=self._bearer(issued["key"])).status_code, 401)

    def test_key_is_never_returned_again(self):
        h = self._admin()
        issued = self.http.post(f"/admin/api-clients/{self.client_id}/keys",
                                json={"kind": "server"}, headers=h).json()
        listed = self.http.get(f"/admin/api-clients/{self.client_id}",
                               headers=h).json()
        blob = str(listed)
        self.assertNotIn(issued["key"], blob)
        self.assertIn(issued["prefix"], blob)

    def test_scope_and_quota_endpoints(self):
        h = self._admin()
        body = self.http.put(f"/admin/api-clients/{self.client_id}/subjects",
                             json={"subject_ids": [self.authored]},
                             headers=h).json()
        self.assertEqual(body["subject_ids"], [self.authored])
        body = self.http.put(f"/admin/api-clients/{self.client_id}/quota",
                             json={"daily_quota": 7}, headers=h).json()
        self.assertEqual(body["daily_quota"], 7)
        body = self.http.put(f"/admin/api-clients/{self.client_id}/status",
                             json={"status": "suspended"}, headers=h).json()
        self.assertEqual(body["status"], "suspended")

    def test_bad_payloads_are_400(self):
        h = self._admin()
        for path, payload in (
            (f"/admin/api-clients/{self.client_id}/status", {"status": "нет"}),
            (f"/admin/api-clients/{self.client_id}/subjects",
             {"subject_ids": [9999]}),
        ):
            self.assertEqual(self.http.put(path, json=payload,
                                           headers=h).status_code, 400)

    def test_delete_client_takes_its_keys(self):
        h = self._admin()
        self.assertEqual(
            self.http.delete(f"/admin/api-clients/{self.client_id}",
                             headers=h).status_code, 200)
        self.assertEqual(
            self.http.get("/v1/me", headers=self._bearer()).status_code, 401)


if __name__ == "__main__":
    unittest.main()
