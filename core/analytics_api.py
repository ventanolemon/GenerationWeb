"""
Агрегированная аналитика преподавателя/админа (GET /analytics/overview).

Чистая логика (headless, как sync_api/graph_api) — HTTP не знает про SQL,
роутер generator_service/routers/analytics.py только адаптирует. Контракт
формы ответа зафиксирован при проектировании визуального слоя (Fable) —
см. scratchpad-контракт сессии; повторён здесь полями totals/timeseries/
correctness_distribution/tasks/students/groups.

Скоуп — Repository.visible_subject_ids (тот же RBAC, что и в sync): teacher
видит системные + свои предметы, admin — все. В отличие от /sync здесь НЕТ
dev-заглушки «видно всё» без identity — аналитика это данные о людях,
роутер отдаёт 401 без X-User-Id.

MVP-оговорка: агрегация делается в Python над выгрузкой attempts по скоупу,
а не оконными SQL-функциями — при академическом масштабе данных (десятки
тысяч попыток на преподавателя) этого достаточно; при росте на порядки
стоит перенести в SQL (оконные функции/материализованные роллапы).
"""

from __future__ import annotations
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .repository import Repository

DAY = 86400.0
_BUCKET_LABELS = ("0–20%", "20–40%", "40–60%", "60–80%", "80–100%")


def overview(
    repo: Repository,
    *,
    user_id: str,
    role: str,
    range_days: int = 30,
    group: Optional[str] = None,
) -> dict:
    range_days = max(1, min(int(range_days or 30), 365))
    now = time.time()
    period_start = now - range_days * DAY
    prev_start = now - 2 * range_days * DAY

    subject_ids = repo.visible_subject_ids(user_id, role)
    subjects, partitions, rows, users = _load(repo, subject_ids)

    if group:
        in_group = {lg for lg, u in users.items() if u["group"] == group}
        rows = [r for r in rows if r[0] in in_group]

    cur_rows = [r for r in rows if r[3] >= period_start]
    prev_rows = [r for r in rows if prev_start <= r[3] < period_start]

    totals, cur_attempts, cur_rate = _totals(cur_rows, prev_rows)
    timeseries = _timeseries(cur_rows)
    students, correctness_distribution = _students(cur_rows, users)
    tasks = _tasks(rows, cur_rows, partitions, subjects, period_start,
                    totals["tasks_active"])
    groups_out = _groups(cur_rows, users, totals["tasks_active"])

    return {
        "generated_at": _iso(now),
        "scope": {"role": role, "owner": user_id, "range_days": range_days,
                  "group": group},
        "totals": totals,
        "timeseries": timeseries,
        "correctness_distribution": correctness_distribution,
        "tasks": tasks,
        "students": students,
        "groups": groups_out,
    }


# ---------- Загрузка скоупа ----------

def _load(repo: Repository, subject_ids: list[int]):
    with repo._connect() as conn:  # noqa: SLF001 — analytics_api это слой данных
        if not subject_ids:
            return {}, {}, [], {}
        ph = ",".join("?" * len(subject_ids))
        subjects = {
            r[0]: r[1] for r in conn.execute(
                f"SELECT id, subject_name FROM Subjects WHERE id IN ({ph})",
                subject_ids,
            ).fetchall()
        }
        partitions = {
            r[0]: {"subject_id": r[1], "name": r[2], "constracted": r[3]}
            for r in conn.execute(
                f"SELECT id, subject_id, partition_name, constracted "
                f"FROM Partitions WHERE subject_id IN ({ph}) AND deleted_at IS NULL",
                subject_ids,
            ).fetchall()
        }
        if not partitions:
            return subjects, partitions, [], {}
        pph = ",".join("?" * len(partitions))
        rows = conn.execute(
            f"SELECT user_id, partition_id, correct, created_at FROM attempts "
            f"WHERE partition_id IN ({pph})",
            list(partitions.keys()),
        ).fetchall()
        logins = {r[0] for r in rows}
        users = {}
        if logins:
            uph = ",".join("?" * len(logins))
            users = {
                r[0]: {"fio": r[1] or "", "group": r[2] or ""}
                for r in conn.execute(
                    f'SELECT login, FIO, "group" FROM users WHERE login IN ({uph})',
                    list(logins),
                ).fetchall()
            }
    return subjects, partitions, rows, users


# ---------- Тоталы ----------

def _rate(rs) -> Optional[float]:
    graded = [r for r in rs if r[2] is not None]
    if not graded:
        return None
    return sum(1 for r in graded if r[2]) / len(graded)


def _totals(cur_rows, prev_rows):
    cur_rate = _rate(cur_rows)
    prev_rate = _rate(prev_rows)
    cur_attempts = len(cur_rows)
    prev_attempts = len(prev_rows)
    attempts_delta_pct = (
        (cur_attempts - prev_attempts) / prev_attempts if prev_attempts else None
    )
    correct_rate_delta = (
        cur_rate - prev_rate if cur_rate is not None and prev_rate is not None
        else None
    )
    totals = {
        "attempts": cur_attempts,
        "students_active": len({r[0] for r in cur_rows}),
        "correct_rate": round(cur_rate, 4) if cur_rate is not None else 0.0,
        "tasks_active": len({r[1] for r in cur_rows}),
        "attempts_delta_pct": (
            round(attempts_delta_pct, 4) if attempts_delta_pct is not None else None
        ),
        "correct_rate_delta": (
            round(correct_rate_delta, 4) if correct_rate_delta is not None else None
        ),
    }
    return totals, cur_attempts, cur_rate


# ---------- Ряд по дням ----------

def _timeseries(cur_rows):
    by_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for _uid, _pid, correct, ts in cur_rows:
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        by_day[day][0] += 1
        if correct:
            by_day[day][1] += 1
    return [
        {"date": d, "attempts": v[0], "correct": v[1]}
        for d, v in sorted(by_day.items())
    ]


# ---------- Студенты + гистограмма личной доли верных ----------

def _status(rate: float) -> str:
    if rate < 0.6:
        return "struggling"
    if rate >= 0.8:
        return "strong"
    return "steady"


def _students(cur_rows, users):
    per_student: dict[str, dict] = defaultdict(
        lambda: {"attempts": 0, "correct": 0, "last_seen": 0.0}
    )
    for uid_, _pid, correct, ts in cur_rows:
        s = per_student[uid_]
        s["attempts"] += 1
        if correct:
            s["correct"] += 1
        if ts > s["last_seen"]:
            s["last_seen"] = ts

    students = []
    dist_counts = [0, 0, 0, 0, 0]
    for login, s in per_student.items():
        rate = s["correct"] / s["attempts"] if s["attempts"] else 0.0
        dist_counts[min(4, int(rate * 5))] += 1
        u = users.get(login, {"fio": "", "group": ""})
        students.append({
            "login": login, "fio": u["fio"], "group": u["group"],
            "attempts": s["attempts"], "correct_rate": round(rate, 4),
            "last_seen": _iso(s["last_seen"]),
            "status": _status(rate),
        })
    students.sort(key=lambda s: s["attempts"], reverse=True)

    correctness_distribution = [
        {"bucket": label, "students": n}
        for label, n in zip(_BUCKET_LABELS, dist_counts)
    ]
    return students, correctness_distribution


# ---------- Задания ----------

def _difficulty(rate: float) -> str:
    if rate >= 0.8:
        return "easy"
    if rate >= 0.55:
        return "medium"
    return "hard"


def _avg_attempts_to_correct(rows) -> dict[int, float]:
    """Среднее число попыток каждого студента до ПЕРВОГО верного ответа
    на задание (всё время, не режется периодом — устойчивая метрика
    сложности, не должна прыгать при смене диапазона в UI)."""
    by_task_student: dict[tuple[int, str], list] = defaultdict(list)
    for uid_, pid_, correct, ts in rows:
        by_task_student[(pid_, uid_)].append((ts, correct))

    per_task_counts: dict[int, list[int]] = defaultdict(list)
    for (pid_, _uid), attempts_ in by_task_student.items():
        attempts_.sort(key=lambda a: a[0])
        n = 0
        for _ts, correct in attempts_:
            n += 1
            if correct:
                per_task_counts[pid_].append(n)
                break

    return {
        pid_: round(sum(counts) / len(counts), 2)
        for pid_, counts in per_task_counts.items()
    }


def _tasks(rows, cur_rows, partitions, subjects, period_start, _tasks_active):
    per_task: dict[int, dict] = defaultdict(
        lambda: {"attempts": 0, "correct": 0, "students": set(),
                  "last_activity": 0.0}
    )
    for uid_, pid_, correct, ts in rows:  # last_activity — всё время
        t = per_task[pid_]
        if ts > t["last_activity"]:
            t["last_activity"] = ts
    for uid_, pid_, correct, ts in cur_rows:  # attempts/correct/students — период
        t = per_task[pid_]
        t["attempts"] += 1
        if correct:
            t["correct"] += 1
        t["students"].add(uid_)

    avg_map = _avg_attempts_to_correct(rows)

    tasks = []
    for pid_, t in per_task.items():
        if t["attempts"] == 0:
            continue
        p = partitions.get(pid_)
        if p is None:
            continue
        rate = t["correct"] / t["attempts"]
        tasks.append({
            "partition_id": pid_, "name": p["name"],
            "subject": subjects.get(p["subject_id"], ""),
            "type": "graph" if p["constracted"] == 4 else "test",
            "attempts": t["attempts"], "correct_rate": round(rate, 4),
            "avg_attempts_to_correct": avg_map.get(pid_),
            "students": len(t["students"]),
            "last_activity": _iso(t["last_activity"]),
            "difficulty": _difficulty(rate),
        })
    tasks.sort(key=lambda t: t["attempts"], reverse=True)
    return tasks


# ---------- Группы ----------

def _groups(cur_rows, users, tasks_active: int):
    per_group: dict[str, dict] = defaultdict(
        lambda: {"students": set(), "attempts": 0, "correct": 0,
                  "solved_tasks": set()}
    )
    for uid_, pid_, correct, ts in cur_rows:
        u = users.get(uid_)
        g = u["group"] if u else ""
        if not g:
            continue
        pg = per_group[g]
        pg["students"].add(uid_)
        pg["attempts"] += 1
        if correct:
            pg["correct"] += 1
            pg["solved_tasks"].add(pid_)

    groups_out = []
    for g, pg in per_group.items():
        rate = pg["correct"] / pg["attempts"] if pg["attempts"] else 0.0
        coverage = len(pg["solved_tasks"]) / tasks_active if tasks_active else 0.0
        groups_out.append({
            "group": g, "students": len(pg["students"]),
            "correct_rate": round(rate, 4), "attempts": pg["attempts"],
            "coverage": round(coverage, 4),
        })
    groups_out.sort(key=lambda g: g["group"])
    return groups_out


# ---------- Утилиты ----------

def _iso(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
