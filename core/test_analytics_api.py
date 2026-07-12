"""
Тесты агрегированной аналитики (core/analytics_api.overview) — headless,
свежая SQLite на каждый тест.

Запуск: python -m unittest core.test_analytics_api  (из корня монорепо)
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import time
import unittest

from core import analytics_api
from core.repository import Repository

DAY = 86400.0


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


class AnalyticsApiTestBase(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        self.repo = Repository(self.db)
        self.now = time.time()
        self._attempt_seq = 0

    def tearDown(self):
        os.unlink(self.db)

    def _attempt(self, login, partition_id, correct, days_ago=0.0, uid=None):
        ts = self.now - days_ago * DAY
        self._attempt_seq += 1
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO attempts "
                "(client_uuid, user_id, partition_id, payload, correct, "
                " device_id, created_at) VALUES (?, ?, ?, '{}', ?, 'dev', ?)",
                (uid or f"a-{login}-{partition_id}-{self._attempt_seq}",
                 login, partition_id,
                 None if correct is None else int(bool(correct)), ts),
            )
            conn.commit()


class EmptyStateTests(AnalyticsApiTestBase):
    def test_no_attempts_returns_zeroed_totals_and_empty_lists(self):
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        self.assertEqual(out["totals"]["attempts"], 0)
        self.assertEqual(out["totals"]["students_active"], 0)
        self.assertEqual(out["totals"]["correct_rate"], 0.0)
        self.assertEqual(out["totals"]["tasks_active"], 0)
        self.assertIsNone(out["totals"]["attempts_delta_pct"])
        self.assertIsNone(out["totals"]["correct_rate_delta"])
        self.assertEqual(out["timeseries"], [])
        self.assertEqual(out["tasks"], [])
        self.assertEqual(out["students"], [])
        self.assertEqual(out["groups"], [])
        self.assertEqual(
            [b["students"] for b in out["correctness_distribution"]], [0] * 5)


class ScopeTests(AnalyticsApiTestBase):
    """Тот же RBAC-скоуп, что в sync: teacher видит системные + свои
    предметы, не чужие; admin — все."""

    def setUp(self):
        super().setUp()
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("s1", "p", "Студент 1", "КСБО-11-24",
                              role="student")
        self.sys_subj = self.repo.ensure_subject(1, "Физика", "Физика")
        self.alla_subj = self.repo.create_subject("Курс Аллы", "x",
                                                   owner_user_id="alla")
        self.boris_subj = self.repo.create_subject("Курс Бориса", "x",
                                                    owner_user_id="boris")
        self.p_sys = self.repo.upsert_partition(self.sys_subj, "Общий", 4, {})
        self.p_alla = self.repo.upsert_partition(self.alla_subj, "Аллы", 4, {})
        self.p_boris = self.repo.upsert_partition(self.boris_subj, "Бориса",
                                                   4, {})
        self._attempt("s1", self.p_sys, True)
        self._attempt("s1", self.p_alla, True)
        self._attempt("s1", self.p_boris, True)

    def test_teacher_sees_own_and_system_not_others(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        pids = {t["partition_id"] for t in out["tasks"]}
        self.assertEqual(pids, {self.p_sys, self.p_alla})
        self.assertEqual(out["totals"]["attempts"], 2)

    def test_admin_sees_all(self):
        out = analytics_api.overview(self.repo, user_id="root", role="admin")
        pids = {t["partition_id"] for t in out["tasks"]}
        self.assertEqual(pids, {self.p_sys, self.p_alla, self.p_boris})
        self.assertEqual(out["totals"]["attempts"], 3)


class TotalsAndTimeseriesTests(AnalyticsApiTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("s1", "p", "С1", "Г1", role="student")
        self.repo.create_user("s2", "p", "С2", "Г1", role="student")
        subj = self.repo.create_subject("Курс", "x", owner_user_id="alla")
        self.pid = self.repo.upsert_partition(subj, "Раздел", 4, {})
        # Текущий период (range_days=30 по умолчанию): 4 попытки, 3 верных.
        self._attempt("s1", self.pid, True, days_ago=1)
        self._attempt("s1", self.pid, True, days_ago=1)
        self._attempt("s2", self.pid, False, days_ago=2)
        self._attempt("s2", self.pid, True, days_ago=2)
        # Предыдущий период (31-60 дней назад): 2 попытки, 1 верная.
        self._attempt("s1", self.pid, True, days_ago=40)
        self._attempt("s2", self.pid, False, days_ago=45)

    def test_totals_correct_rate_and_students_active(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        t = out["totals"]
        self.assertEqual(t["attempts"], 4)
        self.assertEqual(t["students_active"], 2)
        self.assertEqual(t["tasks_active"], 1)
        self.assertAlmostEqual(t["correct_rate"], 0.75)

    def test_deltas_vs_previous_period(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        t = out["totals"]
        # attempts: 4 текущих vs 2 предыдущих → +100%.
        self.assertAlmostEqual(t["attempts_delta_pct"], 1.0)
        # correct_rate: 0.75 текущий vs 0.5 предыдущий → +0.25.
        self.assertAlmostEqual(t["correct_rate_delta"], 0.25)

    def test_timeseries_grouped_by_day_sorted_ascending(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        ts = out["timeseries"]
        self.assertEqual(len(ts), 2)  # days_ago=1 и days_ago=2 — разные дни
        self.assertEqual([p["date"] for p in ts], sorted(p["date"] for p in ts))
        self.assertEqual(sum(p["attempts"] for p in ts), 4)
        self.assertEqual(sum(p["correct"] for p in ts), 3)


class StudentsAndDistributionTests(AnalyticsApiTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("s1", "p", "Иванов", "Г1", role="student")
        self.repo.create_user("s2", "p", "Петров", "Г1", role="student")
        subj = self.repo.create_subject("Курс", "x", owner_user_id="alla")
        self.pid = self.repo.upsert_partition(subj, "Раздел", 4, {})
        # s1: 10 попыток, 9 верных → 0.9 → strong.
        for i in range(9):
            self._attempt("s1", self.pid, True, days_ago=1, uid=f"s1-ok-{i}")
        self._attempt("s1", self.pid, False, days_ago=1, uid="s1-bad")
        # s2: 10 попыток, 3 верных → 0.3 → struggling.
        for i in range(3):
            self._attempt("s2", self.pid, True, days_ago=1, uid=f"s2-ok-{i}")
        for i in range(7):
            self._attempt("s2", self.pid, False, days_ago=1, uid=f"s2-bad-{i}")

    def test_student_status_and_fields(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        by_login = {s["login"]: s for s in out["students"]}
        self.assertEqual(by_login["s1"]["status"], "strong")
        self.assertEqual(by_login["s1"]["fio"], "Иванов")
        self.assertEqual(by_login["s1"]["group"], "Г1")
        self.assertAlmostEqual(by_login["s1"]["correct_rate"], 0.9)
        self.assertEqual(by_login["s2"]["status"], "struggling")
        self.assertAlmostEqual(by_login["s2"]["correct_rate"], 0.3)

    def test_correctness_distribution_buckets(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        dist = {b["bucket"]: b["students"] for b in out["correctness_distribution"]}
        self.assertEqual(dist["20–40%"], 1)   # s2 = 0.3
        self.assertEqual(dist["80–100%"], 1)  # s1 = 0.9
        self.assertEqual(sum(dist.values()), 2)


class TaskDifficultyAndAvgAttemptsTests(AnalyticsApiTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("s1", "p", "С1", "Г1", role="student")
        subj = self.repo.create_subject("Курс", "x", owner_user_id="alla")
        self.p_graph = self.repo.upsert_partition(subj, "Граф-раздел", 4, {})
        self.p_test = self.repo.upsert_partition(subj, "Тест-раздел", 3, {})

    def test_type_derived_from_constracted(self):
        self._attempt("s1", self.p_graph, True, days_ago=1)
        self._attempt("s1", self.p_test, True, days_ago=1)
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        by_pid = {t["partition_id"]: t for t in out["tasks"]}
        self.assertEqual(by_pid[self.p_graph]["type"], "graph")
        self.assertEqual(by_pid[self.p_test]["type"], "test")

    def test_difficulty_thresholds(self):
        # 9/10 верных → 0.9 → easy.
        for i in range(9):
            self._attempt("s1", self.p_graph, True, days_ago=1, uid=f"ok-{i}")
        self._attempt("s1", self.p_graph, False, days_ago=1, uid="bad")
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        task = next(t for t in out["tasks"] if t["partition_id"] == self.p_graph)
        self.assertEqual(task["difficulty"], "easy")

    def test_avg_attempts_to_correct_counts_up_to_first_success(self):
        # s1: неверно, неверно, верно → 3 попытки до первого успеха.
        self._attempt("s1", self.p_graph, False, days_ago=1, uid="t1")
        self._attempt("s1", self.p_graph, False, days_ago=1, uid="t2")
        self._attempt("s1", self.p_graph, True, days_ago=1, uid="t3")
        # Попытка ПОСЛЕ первого успеха не должна учитываться в среднем.
        self._attempt("s1", self.p_graph, False, days_ago=0.5, uid="t4")
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        task = next(t for t in out["tasks"] if t["partition_id"] == self.p_graph)
        self.assertAlmostEqual(task["avg_attempts_to_correct"], 3.0)

    def test_last_activity_not_clipped_by_range(self):
        # Активность 40 дней назад (вне периода 30 дней) — не должна попасть
        # в attempts периода, но обязана остаться в last_activity.
        self._attempt("s1", self.p_graph, True, days_ago=40, uid="old")
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher",
                                     range_days=7)
        self.assertEqual(out["tasks"], [])  # вне периода — не "активно"
        # Прямая проверка last_activity через более широкий период.
        out2 = analytics_api.overview(self.repo, user_id="alla", role="teacher",
                                      range_days=60)
        task = next(t for t in out2["tasks"] if t["partition_id"] == self.p_graph)
        self.assertNotEqual(task["last_activity"], "")


class GroupFilterAndRollupTests(AnalyticsApiTestBase):
    def setUp(self):
        super().setUp()
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("s1", "p", "С1", "Г1", role="student")
        self.repo.create_user("s2", "p", "С2", "Г2", role="student")
        subj = self.repo.create_subject("Курс", "x", owner_user_id="alla")
        self.pid = self.repo.upsert_partition(subj, "Раздел", 4, {})
        self._attempt("s1", self.pid, True, days_ago=1)
        self._attempt("s1", self.pid, True, days_ago=1)
        self._attempt("s2", self.pid, False, days_ago=1)

    def test_group_query_param_narrows_scope(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher",
                                     group="Г1")
        logins = {s["login"] for s in out["students"]}
        self.assertEqual(logins, {"s1"})
        self.assertEqual(out["totals"]["attempts"], 2)

    def test_groups_rollup_coverage(self):
        out = analytics_api.overview(self.repo, user_id="alla", role="teacher")
        by_group = {g["group"]: g for g in out["groups"]}
        self.assertEqual(by_group["Г1"]["students"], 1)
        self.assertEqual(by_group["Г1"]["attempts"], 2)
        self.assertAlmostEqual(by_group["Г1"]["correct_rate"], 1.0)
        # Г1 решила единственное активное задание → coverage 1.0.
        self.assertAlmostEqual(by_group["Г1"]["coverage"], 1.0)
        # Г2 ничего не решила (0 верных) → coverage 0.0.
        self.assertAlmostEqual(by_group["Г2"]["coverage"], 0.0)


class RouterTests(AnalyticsApiTestBase):
    """Тонкий HTTP-адаптер (generator_service/routers/analytics.py):
    401 без identity, 200 с корректной формой ответа."""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import analytics as analytics_router

        app = FastAPI()
        app.include_router(analytics_router.router)
        app.state.repo = self.repo
        return TestClient(app)

    def test_401_without_identity(self):
        r = self._client().get("/analytics/overview")
        self.assertEqual(r.status_code, 401)

    def test_200_with_identity_returns_contract_shape(self):
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        r = self._client().get(
            "/analytics/overview",
            headers={"X-User-Id": "alla", "X-User-Role": "teacher"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ("generated_at", "scope", "totals", "timeseries",
                    "correctness_distribution", "tasks", "students", "groups"):
            self.assertIn(key, data)
        self.assertEqual(data["scope"]["owner"], "alla")
        self.assertEqual(data["scope"]["range_days"], 30)


if __name__ == "__main__":
    unittest.main()
