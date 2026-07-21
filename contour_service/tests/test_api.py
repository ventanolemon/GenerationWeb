"""
API-тест полного цикла через FastAPI TestClient (реальные HTTP-семантики,
без сети): POST /contour/jobs → воркер (синхронно) → GET (awaiting_human,
превью/флаги/вердикт) → POST approve → партиция constracted=4 + корпусная
запись human.approved=true. Плюс владение (чужая джоба невидима) и роли.

Интеграционные тесты (живой Postgres / живой Anthropic) — в конце, скипаются
без CONTOUR_PG_DSN / ANTHROPIC_API_KEY: pytest в окружении монорепо нет,
эквивалент @pytest.mark.integration — unittest.skipUnless по env.
"""

from __future__ import annotations
import json
import os
import tempfile
import unittest

from .helpers import make_env  # noqa: F401  (sys.path монорепо)

from fastapi.testclient import TestClient

from contour_service import main as contour_main
from contour_service.providers import MockProvider, TASK_CRITIC, TASK_GENERATE
from contour_service.providers.mock import graph_response
from contour_service.worker import process_one
from exercises.graph_examples import EXAMPLES

PHYSICS = EXAMPLES["physics_force"]["graph"]

# X-User-Id — логин-строка (канонический id, единый с десктопом).
TEACHER = {"X-User-Id": "alla", "X-User-Role": "teacher"}
OTHER_TEACHER = {"X-User-Id": "boris", "X-User-Role": "teacher"}
ADMIN = {"X-User-Id": "root", "X-User-Role": "admin"}
STUDENT = {"X-User-Id": "stud", "X-User-Role": "student"}


class ApiFullCycleTests(unittest.TestCase):
    """S6-флоу поверх реального приложения (lifespan, изолированная БД)."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        os.environ["CONTOUR_DB_PATH"] = self._tmp.name
        os.environ["CONTOUR_WORKER_DISABLED"] = "1"
        os.environ["CONTOUR_PROVIDER"] = "mock"
        self.client = TestClient(contour_main.app)
        self.client.__enter__()                      # lifespan
        app = contour_main.app
        # Скриптованные провайдеры вместо дефолтных заглушек.
        reg = app.state.contour_providers
        reg.register(MockProvider(TASK_GENERATE, [graph_response(PHYSICS)]))
        reg.register(MockProvider(
            TASK_CRITIC,
            [{"verdict": "accept", "failures": [], "confidence": 0.85,
              "summary": "Задание корректно и разнообразно."}]))
        # Предмет для будущей партиции.
        app.state.repo.ensure_subject(3, "Физика (тест контура)")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for var in ("CONTOUR_DB_PATH", "CONTOUR_WORKER_DISABLED",
                    "CONTOUR_PROVIDER"):
            os.environ.pop(var, None)
        os.unlink(self._tmp.name)

    def _run_worker(self):
        app = contour_main.app
        return process_one(app.state.contour_queue, app.state.contour_deps, "t")

    def test_full_cycle_to_approved_partition_and_corpus(self):
        # 1. Создание джобы (202, queued).
        resp = self.client.post("/contour/jobs", headers=TEACHER, json={
            "description": "Задачи на силу F=ma по физике",
            "subject_id": 3,
        })
        self.assertEqual(resp.status_code, 202, resp.text)
        job_id = resp.json()["job_id"]
        self.assertEqual(resp.json()["status"], "queued")

        # 2. Воркер прогоняет петлю (синхронно — встроенный отключён).
        self.assertTrue(self._run_worker())

        # 3. Поллинг: awaiting_human, превью заданий и вердикт на месте.
        resp = self.client.get(f"/contour/jobs/{job_id}", headers=TEACHER)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "awaiting_human")
        self.assertGreaterEqual(len(body["previews"]), 3)
        self.assertTrue(all(p["statement"] for p in body["previews"]))
        self.assertEqual(body["critic"]["verdict"], "accept")
        self.assertEqual(len(body["rounds"]), 1)
        self.assertNotIn("graph", body["rounds"][0], "раунды в ответе компактны")

        # Полный probe-отчёт для веб-экрана S6: таблица прогонов и агрегаты.
        self.assertIn("probe", body)
        self.assertGreaterEqual(len(body["probe"]["runs"]), 3)
        run0 = body["probe"]["runs"][0]
        for key in ("seed", "statement", "answer", "attempts", "wall_ms", "error"):
            self.assertIn(key, run0)
        agg = body["probe"]["aggregates"]
        self.assertIn("attempts_p50", agg)
        self.assertIn("distinct_statements", agg)

        # 4. Утверждение: партиция constracted=4 + корпус generate.
        resp = self.client.post(f"/contour/jobs/{job_id}/approve",
                                headers=TEACHER,
                                json={"partition_name": "Сила (контур)"})
        self.assertEqual(resp.status_code, 200, resp.text)
        approved = resp.json()
        self.assertEqual(approved["status"], "approved")
        self.assertFalse(approved["corpus_deduplicated"])

        app = contour_main.app
        part = app.state.repo.get_partition(approved["partition_id"])
        self.assertIsNotNone(part)
        self.assertEqual(part.constracted, 4)
        self.assertEqual(part.generation_params, PHYSICS,
                         "graph уходит в партицию ДОСЛОВНО (GraphSpec.to_dict)")

        # Корпус: kind=generate, human.approved, probe/каталог в provenance.
        row = app.state.contour_queue.conn.execute(
            "SELECT record FROM corpus_records WHERE kind='generate'"
        ).fetchone()
        self.assertIsNotNone(row, "инвариант: approve пишет корпус")
        record = json.loads(row["record"])
        prov = record["provenance"]
        self.assertTrue(prov["human"]["approved"])
        self.assertTrue(prov["validator"]["passed"])
        self.assertGreater(len(prov["validator"]["seeds"]), 0)
        self.assertTrue(prov["catalog_version"])
        self.assertEqual(record["target_graph"], PHYSICS)

        # 5. Повторное утверждение невозможно (статус уже approved).
        resp = self.client.post(f"/contour/jobs/{job_id}/approve",
                                headers=TEACHER, json={})
        self.assertEqual(resp.status_code, 409)

    def test_ownership_and_roles(self):
        resp = self.client.post("/contour/jobs", headers=TEACHER, json={
            "description": "Мои задачи", "subject_id": 3})
        job_id = resp.json()["job_id"]

        # Чужой teacher джобу не видит (404), admin — видит.
        self.assertEqual(
            self.client.get(f"/contour/jobs/{job_id}",
                            headers=OTHER_TEACHER).status_code, 404)
        self.assertEqual(
            self.client.get(f"/contour/jobs/{job_id}",
                            headers=ADMIN).status_code, 200)

        # student не может запускать контур; без заголовка — 401.
        self.assertEqual(
            self.client.post("/contour/jobs", headers=STUDENT, json={
                "description": "хочу задание", "subject_id": 3}).status_code, 403)
        self.assertEqual(
            self.client.post("/contour/jobs", json={
                "description": "хочу задание", "subject_id": 3}).status_code, 401)

    def test_reject_writes_escalation_log(self):
        resp = self.client.post("/contour/jobs", headers=TEACHER, json={
            "description": "Задачи на силу", "subject_id": 3})
        job_id = resp.json()["job_id"]
        self._run_worker()

        resp = self.client.post(f"/contour/jobs/{job_id}/reject",
                                headers=TEACHER,
                                json={"reason": "слишком просто"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "rejected")

        app = contour_main.app
        row = app.state.contour_queue.conn.execute(
            "SELECT record FROM corpus_records WHERE kind='escalation'"
        ).fetchone()
        record = json.loads(row["record"])
        self.assertIn("слишком просто", record["reason"])


@unittest.skipUnless(os.environ.get("CONTOUR_PG_DSN"),
                     "интеграционный: нужен живой Postgres (CONTOUR_PG_DSN)")
class PostgresQueueIntegrationTests(unittest.TestCase):
    """Живой FOR UPDATE SKIP LOCKED (эквивалент @pytest.mark.integration)."""

    def test_concurrent_claim_no_double_take(self):
        from contour_service.db import apply_migrations
        from contour_service.queue import PostgresJobQueue
        q1 = PostgresJobQueue(os.environ["CONTOUR_PG_DSN"])
        q2 = PostgresJobQueue(os.environ["CONTOUR_PG_DSN"])
        apply_migrations(q1.conn)
        job_id = q1.enqueue(1, 3, "конкурентная")
        a = q1.claim("w1")
        b = q2.claim("w2")
        self.assertEqual(a["id"], job_id)
        self.assertTrue(b is None or b["id"] != job_id,
                        "SKIP LOCKED: вторая claim не берёт ту же строку")


@unittest.skipUnless(os.environ.get("ANTHROPIC_API_KEY"),
                     "интеграционный: нужен ANTHROPIC_API_KEY")
class AnthropicProviderIntegrationTests(unittest.TestCase):
    """Живой вызов LLM — только вручную/на стенде, не в CI."""

    def test_generate_returns_parseable_graph(self):
        from contour_service.grounding import FewShotPool, compact_catalog
        from contour_service.prompts import build_generator_system
        from contour_service.providers import AnthropicProvider
        cv, catalog = compact_catalog()
        pool = FewShotPool.from_graph_examples()
        system = build_generator_system(
            cv, catalog, pool.select("сила по физике", 2))
        provider = AnthropicProvider("llm.generate_graph")
        out = provider.invoke({"system": system,
                               "user": "Задачи: сила F=ma, целые числа."})
        self.assertIsInstance(out.get("graph"), dict)


if __name__ == "__main__":
    unittest.main()
