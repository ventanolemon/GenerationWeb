"""
Тесты петли S0–S5: полный цикл, repair-раунд seed-rep-001, бюджеты V/R,
инварианты контракта (closed_loop_contract.md §6). Headless, без сети —
LLM-провайдеры замоканы детерминированными скриптами.

Запуск:  python -m unittest discover contour_service/tests -v
"""

from __future__ import annotations
import json
import unittest

from .helpers import (
    SEED_REP_001_BROKEN, SEED_REP_001_DESCRIPTION, SEED_REP_001_ERROR,
    SEED_REP_001_FIXED, make_env,
)

from contour_service.config import ContourConfig
from contour_service.loop import run_pipeline
from contour_service.providers import ProviderError
from contour_service.providers.mock import graph_response
from contour_service.worker import process_one
from exercises.graph_examples import EXAMPLES

PHYSICS = EXAMPLES["physics_force"]["graph"]

ACCEPT = {"verdict": "accept", "failures": [], "confidence": 0.9,
          "summary": "Принято."}


def _job(queue, description="Задачи на силу F=ma по физике"):
    job_id = queue.enqueue(1, 3, description)
    return queue.claim("test-worker"), job_id


class FullCycleTests(unittest.TestCase):
    """queued → generating → validating → critic → awaiting_human."""

    def test_happy_path_reaches_awaiting_human(self):
        queue, deps, conn, gen, critic = make_env(
            [graph_response(PHYSICS)], [ACCEPT])
        job, job_id = _job(queue)
        statuses = []
        out = run_pipeline(job, deps, on_status=statuses.append)

        self.assertEqual(out.status, "awaiting_human")
        self.assertEqual(len(out.rounds), 1)
        self.assertEqual(out.rounds[0]["kind"], "generate")
        self.assertIsNone(out.rounds[0]["stage_failed"])
        self.assertEqual(out.result_graph, PHYSICS)
        # Статусы петли в порядке контура (contour_integration §2).
        self.assertEqual(statuses, ["generating", "validating", "critic"])
        # Probe исполнен на всех K seed, отчёт живой.
        agg = out.result_probe["aggregates"]
        self.assertEqual(agg["runs_ok"], agg["runs_total"])
        self.assertGreater(agg["distinct_statements"], 1)

    def test_worker_persists_outcome_and_unlocks(self):
        queue, deps, conn, gen, critic = make_env(
            [graph_response(PHYSICS)], [ACCEPT])
        job_id = queue.enqueue(1, 3, "Сила по физике")
        self.assertTrue(process_one(queue, deps, "w1"))
        job = queue.get(job_id)
        self.assertEqual(job["status"], "awaiting_human")
        self.assertIsNone(job["locked_by"])
        self.assertEqual(job["result_graph"], PHYSICS)
        self.assertEqual(len(job["rounds"]), 1)
        self.assertIsNotNone(job["critic"])
        # Очередь пуста — второй вызов ничего не берёт.
        self.assertFalse(process_one(queue, deps, "w1"))

    def test_provider_outage_fails_job_without_burning_budget(self):
        # Отказ LLM — не ошибка графа (contour_integration §5): failed, не
        # escalated, и никакие repair-раунды не начинались.
        cfg = ContourConfig()
        cfg.provider_retries = 1
        queue, deps, conn, gen, critic = make_env(None, None, cfg)
        gen._fail_left = 99            # провайдер лежит дольше, чем ретраи
        job_id = queue.enqueue(1, 3, "Любое описание")
        self.assertTrue(process_one(queue, deps, "w1"))
        job = queue.get(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("провайдер", job["error"])
        self.assertEqual(job["rounds"], [])


class RepairRoundTests(unittest.TestCase):
    """Воспроизведение seed-rep-001-broken-wire: битый провод s:res."""

    def test_verbatim_error_and_full_graph_in_repair_message(self):
        queue, deps, conn, gen, critic = make_env(
            [graph_response(SEED_REP_001_BROKEN),
             graph_response(SEED_REP_001_FIXED)],
            [ACCEPT])
        job, job_id = _job(queue, SEED_REP_001_DESCRIPTION)
        out = run_pipeline(job, deps)

        self.assertEqual(out.status, "awaiting_human")
        self.assertEqual(out.result_graph, SEED_REP_001_FIXED)
        # Генератор звался дважды; второй вызов — repair-сообщение.
        self.assertEqual(len(gen.calls), 2)
        repair = json.loads(gen.calls[1]["user"])
        # Формат closed_loop_contract.md §2 — дословно.
        self.assertEqual(repair["stage"], "build")
        self.assertEqual(repair["round"], 1)
        self.assertEqual(
            [e["text"] for e in repair["errors"]], [SEED_REP_001_ERROR],
            "текст GraphValidationError обязан уходить ДОСЛОВНО")
        self.assertEqual(repair["previous_graph"], SEED_REP_001_BROKEN,
                         "repair несёт ПОЛНЫЙ предыдущий граф, не диф")
        self.assertIn("ПОЛНЫЙ граф", repair["instruction"])

    def test_successful_repair_round_writes_corpus_record(self):
        queue, deps, conn, gen, critic = make_env(
            [graph_response(SEED_REP_001_BROKEN),
             graph_response(SEED_REP_001_FIXED)],
            [ACCEPT])
        job, job_id = _job(queue, SEED_REP_001_DESCRIPTION)
        run_pipeline(job, deps)

        self.assertEqual(deps.corpus.count("repair"), 1)
        row = conn.execute(
            "SELECT record, graph_hash FROM corpus_records WHERE kind='repair'"
        ).fetchone()
        record = json.loads(row["record"])
        # Схема training_example_schema.json: kind/input/target/provenance.
        self.assertEqual(record["kind"], "repair")
        self.assertEqual(record["input"]["description"], SEED_REP_001_DESCRIPTION)
        self.assertEqual(record["input"]["prior_graph"], SEED_REP_001_BROKEN)
        self.assertEqual(record["input"]["errors"], [SEED_REP_001_ERROR])
        self.assertEqual(record["target_graph"], SEED_REP_001_FIXED)
        # Инварианты №3/№4: probe-отчёт был (validator.seeds непуст),
        # catalog_version и engine_commit присутствуют.
        prov = record["provenance"]
        self.assertTrue(prov["validator"]["passed"])
        self.assertGreater(len(prov["validator"]["seeds"]), 0)
        self.assertTrue(prov["catalog_version"])
        self.assertTrue(prov["engine_commit"])
        self.assertIsNotNone(row["graph_hash"])

    def test_critic_never_sees_invalid_graph(self):
        # Инвариант №1: битая попытка не доходит до критика — он зовётся
        # один раз, уже с починенным графом и живым probe.
        queue, deps, conn, gen, critic = make_env(
            [graph_response(SEED_REP_001_BROKEN),
             graph_response(SEED_REP_001_FIXED)],
            [ACCEPT])
        job, job_id = _job(queue, SEED_REP_001_DESCRIPTION)
        run_pipeline(job, deps)

        self.assertEqual(len(critic.calls), 1)
        seen = critic.calls[0]["input"]
        self.assertEqual(seen["graph"], SEED_REP_001_FIXED)
        agg = seen["probe"]["aggregates"]
        self.assertEqual(agg["runs_ok"], agg["runs_total"])


class BudgetTests(unittest.TestCase):
    """Исчерпание бюджетов V/R → эскалация, не бесконечный цикл."""

    def test_v_budget_exhaustion_escalates(self):
        # Генератор упорно возвращает битый граф: 1 исходный + V repair-попыток,
        # следующий структурный провал — эскалация.
        queue, deps, conn, gen, critic = make_env(
            [graph_response(SEED_REP_001_BROKEN)],   # повтор последнего ответа
            [ACCEPT])
        job, job_id = _job(queue)
        out = run_pipeline(job, deps)

        self.assertEqual(out.status, "escalated")
        self.assertIn("структурно не сходится", out.error)
        v = deps.config.v_budget
        self.assertEqual(len(gen.calls), 1 + v, "S1: исходный + V repair-раундов")
        self.assertEqual(len(critic.calls), 0,
                         "критик не видел ни одного невалидного графа")
        # Эскалация — штатный выход: лог целиком в corpus_records.
        self.assertEqual(deps.corpus.count("escalation"), 1)

    def test_r_budget_exhaustion_escalates(self):
        revise = {
            "verdict": "revise", "confidence": 0.8, "summary": "Ответ не следует из условия.",
            "failures": [{
                "code": "A1", "severity": "block",
                "evidence": "seed 0: ответ «Предел равен 1.» при условии с tan(x)",
                "fix_hint": "проведи провод от источника условия к узлу ответа",
            }],
        }
        queue, deps, conn, gen, critic = make_env(
            [graph_response(PHYSICS)], [revise])
        job, job_id = _job(queue)
        out = run_pipeline(job, deps)

        self.assertEqual(out.status, "escalated")
        self.assertIn("качество не сходится", out.error)
        r = deps.config.r_budget
        # Каждый revise → новый S1-раунд; критик звался 1 + R раз.
        self.assertEqual(len(critic.calls), 1 + r)
        self.assertEqual(len(gen.calls), 1 + r)
        # fix_hint критика ушёл генератору дословно (repair stage=critic).
        repair = json.loads(gen.calls[1]["user"])
        self.assertEqual(repair["stage"], "critic")
        self.assertEqual(repair["errors"][0]["text"],
                         revise["failures"][0]["fix_hint"])
        self.assertEqual(repair["errors"][0]["code"], "A1")

    def test_reject_escalates_immediately(self):
        reject = {"verdict": "reject", "confidence": 0.9, "summary": "Не та тема.",
                  "failures": [{"code": "C1", "severity": "block",
                                "evidence": "seed 0: условие про матрицы, а просили пределы",
                                "fix_hint": ""}]}
        queue, deps, conn, gen, critic = make_env(
            [graph_response(PHYSICS)], [reject])
        job, job_id = _job(queue)
        out = run_pipeline(job, deps)
        self.assertEqual(out.status, "escalated")
        self.assertEqual(len(gen.calls), 1)


class LlmJsonFailureTests(unittest.TestCase):
    def test_non_json_reply_burns_v_and_repairs(self):
        # Невалидный JSON от LLM — ошибка графа (жжёт V), уходит в repair.
        queue, deps, conn, gen, critic = make_env(
            [{"text": "Вот ваш граф: конечно!"},
             graph_response(PHYSICS)],
            [ACCEPT])
        job, job_id = _job(queue)
        out = run_pipeline(job, deps)
        self.assertEqual(out.status, "awaiting_human")
        repair = json.loads(gen.calls[1]["user"])
        self.assertEqual(repair["stage"], "build")
        self.assertIn("не является валидным JSON", repair["errors"][0]["text"])


if __name__ == "__main__":
    unittest.main()
