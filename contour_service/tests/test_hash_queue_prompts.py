"""
Тесты graph_hash (канонический дедуп), job-очереди и промптов/нормализации
вердикта критика. Headless.
"""

from __future__ import annotations
import json
import unittest

from .helpers import SEED_REP_001_FIXED, make_env

from contour_service.corpus import CorpusStore
from contour_service.db import apply_migrations, connect_sqlite
from contour_service.graph_hash import canonical_graph_hash
from contour_service.grounding import FewShotPool, compact_catalog
from contour_service.loop import normalize_critic
from contour_service.prompts import (
    CRITIC_SYSTEM, TAXONOMY, build_critic_input, build_generator_system,
    build_repair_message,
)
from contour_service.providers import ProviderRegistry, MockProvider
from contour_service.queue import PostgresJobQueue, SqliteJobQueue


def _renamed(spec: dict, mapping: dict[str, str]) -> dict:
    """Переименовать id узлов графа (семантика не меняется)."""
    def ep(s: str) -> str:
        node, _, port = s.partition(":")
        return f"{mapping.get(node, node)}:{port}"
    return {
        "version": spec.get("version", 1),
        "nodes": [{**n, "id": mapping.get(n["id"], n["id"])}
                  for n in spec["nodes"]],
        "edges": [{"from": ep(e["from"]), "to": ep(e["to"])}
                  for e in spec["edges"]],
        "meta": dict(spec.get("meta") or {}),
    }


class GraphHashTests(unittest.TestCase):
    def test_rename_and_reorder_invariant(self):
        # Требование брифа: одинаковые по семантике графы с разными id
        # узлов дают ОДИН хэш.
        a = SEED_REP_001_FIXED
        b = _renamed(a, {"v": "speed", "t": "duration", "s": "dist",
                         "cond": "c1", "ans": "a1", "task": "final"})
        b["nodes"] = list(reversed(b["nodes"]))
        b["edges"] = list(reversed(b["edges"]))
        self.assertEqual(canonical_graph_hash(a), canonical_graph_hash(b))

    def test_meta_is_ignored(self):
        a = dict(SEED_REP_001_FIXED)
        b = {**SEED_REP_001_FIXED, "meta": {"seed": 42, "max_attempts": 7}}
        self.assertEqual(canonical_graph_hash(a), canonical_graph_hash(b))

    def test_param_change_changes_hash(self):
        b = json.loads(json.dumps(SEED_REP_001_FIXED))
        b["nodes"][0]["params"]["max"] = 16
        self.assertNotEqual(canonical_graph_hash(SEED_REP_001_FIXED),
                            canonical_graph_hash(b))

    def test_edge_change_changes_hash(self):
        b = json.loads(json.dumps(SEED_REP_001_FIXED))
        b["edges"] = [e for e in b["edges"] if e["from"] != "t:out"
                      or e["to"] != "cond:t"]
        self.assertNotEqual(canonical_graph_hash(SEED_REP_001_FIXED),
                            canonical_graph_hash(b))

    def test_corpus_dedup_by_hash(self):
        # Дедуп — UNIQUE-чек при вставке: второй семантически тот же граф
        # (другие id) в тот же kind не вставляется.
        conn = connect_sqlite(":memory:")
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO contour_jobs (id, created_by, subject_id, description,"
            " status, rounds, created_at, updated_at) "
            "VALUES ('j1', 1, 3, 'd', 'queued', '[]', '2026', '2026')")
        store = CorpusStore(conn)
        probe = {"seeds": [0], "runs": [], "flags": [],
                 "aggregates": {"runs_ok": 1, "runs_total": 1, "attempts_max": 1}}
        first = store.write_generate(
            "j1", "описание", None, SEED_REP_001_FIXED, probe, None,
            catalog_version="cv", engine_commit="ec")
        clone = _renamed(SEED_REP_001_FIXED, {"v": "x1", "task": "fin"})
        second = store.write_generate(
            "j1", "другое описание того же", None, clone, probe, None,
            catalog_version="cv", engine_commit="ec")
        self.assertIsNotNone(first)
        self.assertIsNone(second, "дубль по graph_hash должен быть пропущен")
        self.assertEqual(store.count("generate"), 1)


class QueueTests(unittest.TestCase):
    def test_claim_locks_and_empties(self):
        queue, deps, conn, gen, critic = make_env()
        a = queue.enqueue(1, 3, "первая")
        b = queue.enqueue(1, 3, "вторая")
        j1 = queue.claim("w1")
        self.assertEqual(j1["id"], a, "FIFO: старейшая queued первой")
        self.assertEqual(j1["status"], "generating")
        self.assertEqual(j1["locked_by"], "w1")
        j2 = queue.claim("w2")
        self.assertEqual(j2["id"], b)
        self.assertIsNone(queue.claim("w3"), "очередь пуста")

    def test_reclaim_stale_returns_to_queue(self):
        queue, deps, conn, gen, critic = make_env()
        queue.enqueue(1, 3, "зависшая")
        job = queue.claim("w1")
        self.assertEqual(queue.reclaim_stale(older_than_s=-1), 1)
        again = queue.claim("w2")
        self.assertEqual(again["id"], job["id"])

    def test_update_roundtrips_json_fields(self):
        queue, deps, conn, gen, critic = make_env()
        job_id = queue.enqueue(1, 3, "джоба")
        queue.update(job_id, rounds=[{"n": 1}], result_graph={"nodes": []})
        job = queue.get(job_id)
        self.assertEqual(job["rounds"], [{"n": 1}])
        self.assertEqual(job["result_graph"], {"nodes": []})

    def test_owner_visibility(self):
        queue, deps, conn, gen, critic = make_env()
        mine = queue.enqueue(1, 3, "моя")
        queue.enqueue(2, 3, "чужая")
        own = queue.list_for_user(1, "teacher")
        self.assertEqual([j["id"] for j in own], [mine])
        self.assertEqual(len(queue.list_for_user(1, "admin")), 2)

    def test_postgres_claim_uses_skip_locked(self):
        # Боевая очередь конкурентна через FOR UPDATE SKIP LOCKED
        # (system_topology §4). Сервера PG в юнит-окружении нет — фиксируем
        # сам SQL; живой прогон — интеграционный тест ниже.
        self.assertIn("FOR UPDATE SKIP LOCKED", PostgresJobQueue.CLAIM_SQL)
        self.assertIn("RETURNING", PostgresJobQueue.CLAIM_SQL)


class PromptTests(unittest.TestCase):
    def test_critic_prompt_operationalizes_all_29_codes(self):
        self.assertEqual(len(TAXONOMY), 29, "таксономия — ровно 29 кодов")
        for code in TAXONOMY:
            self.assertIn(code, CRITIC_SYSTEM, f"код {code} отсутствует в промпте")
        # Обязательное правило доказательности — в тексте промпта.
        self.assertIn("evidence", CRITIC_SYSTEM)
        self.assertIn("будет отброшен", CRITIC_SYSTEM)
        # Правило свёртки вердикта.
        self.assertIn("revise", CRITIC_SYSTEM)
        self.assertIn("fix_hint", CRITIC_SYSTEM)

    def test_generator_prompt_grounds_catalog_and_fewshot(self):
        cv, catalog = compact_catalog()
        pool = FewShotPool.from_graph_examples()
        shots = pool.select("Задачи на силу по физике", 2)
        system = build_generator_system(cv, catalog, shots)
        self.assertIn(cv, system)
        self.assertIn("random_natural", system)      # каталог на месте
        self.assertIn("static_task", system)
        self.assertIn("Отвечай только JSON", system)  # шаблон training_plan §2
        self.assertIn("ПРИМЕРЫ", system)
        self.assertIn(shots[0].description[:20], system)
        # Правило «ответ связан проводами с источниками условия» (анти-A1).
        self.assertIn("СВЯЗАН ПРОВОДАМИ", system)

    def test_repair_message_matches_contract(self):
        msg = build_repair_message(
            2, "build", [{"text": "ошибка", "seed": None, "code": None}],
            {"nodes": []})
        self.assertEqual(set(msg), {"round", "stage", "errors",
                                    "previous_graph", "instruction"})
        self.assertEqual(msg["round"], 2)

    def test_critic_input_matches_taxonomy_io(self):
        inp = build_critic_input("описание", {"task_type": "static"},
                                 {"nodes": []}, {"runs": []}, "cv")
        self.assertEqual(set(inp), {"request", "graph", "probe",
                                    "catalog_version"})
        self.assertEqual(inp["request"]["constraints"]["task_type"], "static")


class CriticNormalizationTests(unittest.TestCase):
    def test_failure_without_evidence_is_dropped(self):
        raw = {"verdict": "reject", "confidence": 0.9, "summary": "…",
               "failures": [{"code": "A1", "severity": "block",
                             "evidence": "", "fix_hint": "почини"}]}
        out = normalize_critic(raw)
        self.assertEqual(out["failures"], [], "провал без цитаты не засчитан")
        self.assertEqual(out["verdict"], "accept",
                         "без доказанных провалов вердикт пересчитан в accept")

    def test_block_with_hint_gives_revise(self):
        raw = {"verdict": "accept",       # модель ошиблась — код пересчитает
               "failures": [{"code": "A1", "severity": "block",
                             "evidence": "seed 0: ответ 1 при tan(x)",
                             "fix_hint": "проведи провод"}],
               "confidence": 2.5}
        out = normalize_critic(raw)
        self.assertEqual(out["verdict"], "revise")
        self.assertEqual(out["confidence"], 1.0, "confidence зажат в [0,1]")

    def test_block_without_hint_gives_reject(self):
        raw = {"verdict": "revise",
               "failures": [{"code": "C1", "severity": "block",
                             "evidence": "условие про матрицы", "fix_hint": ""}],
               "confidence": 0.5}
        self.assertEqual(normalize_critic(raw)["verdict"], "reject")

    def test_warn_only_gives_accept(self):
        raw = {"verdict": "revise",
               "failures": [{"code": "E1", "severity": "warn",
                             "evidence": "ответ 123456", "fix_hint": ""}],
               "confidence": 0.5}
        self.assertEqual(normalize_critic(raw)["verdict"], "accept")


if __name__ == "__main__":
    unittest.main()
