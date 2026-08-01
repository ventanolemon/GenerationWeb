"""
Контракт HTTP-API: единый конверт ошибки и заморозка форм ответов
(этап 0 из public_api.md).

Смысл файла — не «проверить, что работает», а **зафиксировать форму**.
Публичный API начинается с обещания совместимости, а обещание, которое
никто не стережёт, живёт до первого рефакторинга. Тесты ниже перечисляют
ключи ответов поимённо: любое молчаливое переименование или пропажа поля
роняет сборку, и это единственный способ заметить слом раньше интегратора.

Приложение здесь собирается из роутеров, а НЕ импортом
`generator_service.main`: тот тянет `bootstrap` → `exercises`, которым
нужны и словари, и Python 3.12+. Обработчики ошибок ставятся тем же
`errors.install`, что и в бою, поэтому конверт проверяется настоящий.

Запуск: python -m unittest core.test_api_contract -v  (из корня монорепо)
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

from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import grants as grants_router  # noqa: E402
from generator_service.routers import sync as sync_router  # noqa: E402


class _StubRegistry:
    def has(self, _partition_id) -> bool:
        return False


class ContractTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.subject_id = self.repo.ensure_subject(3, "Физика")

        app = FastAPI()
        errors.install(app)
        app.include_router(grants_router.router)
        app.include_router(sync_router.router)

        @app.get("/boom")
        def _boom():
            raise RuntimeError("что-то пошло не так внутри")

        app.state.repo = self.repo
        app.state.registry = _StubRegistry()
        self.app = app
        # raise_server_exceptions=False — иначе TestClient перевыбросит
        # исключение вместо того, чтобы дать посмотреть на ответ 500.
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.unlink(self.db_path)

    @staticmethod
    def _h(login, role):
        return {"X-User-Id": login, "X-User-Role": role}


# ---------- Конверт ошибки ----------

class ErrorEnvelopeTests(ContractTestBase):
    def test_envelope_shape_is_fixed(self):
        r = self.client.get("/subjects/grants/mine")     # без identity → 401
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertEqual(set(body), {"error", "detail"})
        self.assertEqual(set(body["error"]), {"code", "message", "request_id"})

    def test_codes_are_stable_per_status(self):
        with self.assertLogs("generator_service.errors", "ERROR"):
            boom = self.client.get("/boom")
        cases = [
            (self.client.get("/subjects/grants/mine"), 401, "unauthenticated"),
            (self.client.get("/admin/subject-grants",
                             headers=self._h("alla", "teacher")), 403,
             "forbidden"),
            (self.client.put("/admin/subject-grants/нет-такого",
                             json={"subject_ids": []},
                             headers=self._h("root", "admin")), 400,
             "bad_request"),
            (boom, 500, "internal_error"),
        ]
        for response, status, code in cases:
            with self.subTest(status=status):
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)

    def test_detail_mirrors_message_for_desktop_clients(self):
        # core/grants/client.py и AdminClient десктопа читают именно detail.
        r = self.client.get("/admin/subject-grants",
                            headers=self._h("alla", "teacher"))
        body = r.json()
        self.assertEqual(body["detail"], body["error"]["message"])
        self.assertIn("администратору", body["detail"])

    def test_validation_error_keeps_machine_readable_fields(self):
        r = self.client.post("/sync/pull", json={})      # нет device_id
        self.assertEqual(r.status_code, 422)
        error = r.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertTrue(error["fields"], "поля ошибки не потеряны")
        self.assertEqual(set(error["fields"][0]), {"loc", "type", "message"})

    def test_unhandled_exception_does_not_leak_internals(self):
        with self.assertLogs("generator_service.errors", "ERROR") as logged:
            body = self.client.get("/boom").json()
        # Подробности уходят в лог, а не клиенту.
        self.assertIn("Необработанная ошибка", logged.output[0])
        self.assertNotIn("RuntimeError", body["error"]["message"])
        self.assertNotIn("что-то пошло не так", body["error"]["message"])

    def test_request_id_is_echoed_when_supplied(self):
        r = self.client.get("/subjects/grants/mine",
                            headers={"X-Request-Id": "req-42"})
        self.assertEqual(r.json()["error"]["request_id"], "req-42")
        self.assertEqual(r.headers["X-Request-Id"], "req-42")

    def test_request_id_is_generated_when_absent(self):
        r = self.client.get("/subjects/grants/mine")
        rid = r.json()["error"]["request_id"]
        self.assertTrue(rid)
        self.assertEqual(r.headers["X-Request-Id"], rid)

    def test_successful_responses_carry_no_envelope(self):
        r = self.client.get("/subjects/grants/mine",
                            headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("error", r.json())


# ---------- Замороженные формы ответов ----------

class ResponseShapeTests(ContractTestBase):
    """Ключи перечислены поимённо намеренно: это и есть заморозка."""

    def test_grants_mine(self):
        r = self.client.get("/subjects/grants/mine",
                            headers=self._h("alla", "teacher"))
        self.assertEqual(set(r.json()),
                         {"scope_version", "default_access", "subject_ids"})

    def test_admin_matrix(self):
        body = self.client.get("/admin/subject-grants",
                               headers=self._h("root", "admin")).json()
        self.assertEqual(set(body),
                         {"default_access", "teachers", "subjects", "grants"})
        self.assertEqual(set(body["teachers"][0]), {"login", "fio"})
        self.assertEqual(set(body["subjects"][0]),
                         {"id", "subject_name", "is_builtin"})

    def test_put_grants(self):
        body = self.client.put(
            "/admin/subject-grants/alla",
            json={"subject_ids": [self.subject_id]},
            headers=self._h("root", "admin")).json()
        self.assertEqual(set(body),
                         {"ok", "login", "subject_ids", "scope_version"})

    def test_sync_pull(self):
        body = self.client.post("/sync/pull", json={"device_id": "d"},
                                headers=self._h("alla", "teacher")).json()
        self.assertEqual(
            set(body),
            {"subjects", "partitions", "deleted", "new_cursors", "has_more",
             "resources", "scope_version", "resync"})
        self.assertEqual(set(body["new_cursors"]), {"subjects", "partitions"})
        self.assertEqual(set(body["resources"]), {"catalog_version"})

    def test_sync_push(self):
        body = self.client.post("/sync/push", json={"device_id": "d"},
                                headers=self._h("alla", "teacher")).json()
        self.assertEqual(set(body), {"attempts_received", "attempts_new",
                                     "accepted", "conflicts"})


# ---------- OpenAPI ----------

class OpenApiTests(ContractTestBase):
    def test_spec_builds_and_lists_routes(self):
        # Описание собирается из кода; scripts/export_openapi.py выгружает
        # ровно его. Если сборка спеки падает, ломается и выгрузка наружу.
        spec = self.app.openapi()
        self.assertTrue(spec["openapi"].startswith("3."))
        for path in ("/subjects/grants/mine", "/admin/subject-grants",
                     "/sync/pull", "/sync/push"):
            self.assertIn(path, spec["paths"])

    def test_admin_grants_paths_are_distinct_operations(self):
        # default-access не должен схлопнуться в {login}: это разные ручки.
        paths = self.app.openapi()["paths"]
        self.assertIn("/admin/subject-grants/{login}", paths)
        self.assertIn("/admin/subject-grants/default-access", paths)


if __name__ == "__main__":
    unittest.main()
