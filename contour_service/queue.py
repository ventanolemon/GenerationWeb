"""
Job-очередь контура: таблица contour_jobs И ЕСТЬ очередь
(system_topology.md §4 — Redis/RabbitMQ сознательно не вводятся: очередь
в Postgres транзакционна с персистом раундов и корпуса).

Интерфейс JobQueue — «шов на будущее» из того же документа: замена на
брокер локальна. Две реализации:

  * PostgresJobQueue — боевая: claim через SELECT … FOR UPDATE SKIP LOCKED
    (конкурентные воркеры не дерутся за одну строку и не ждут друг друга);
  * SqliteJobQueue — dev/тесты: SKIP LOCKED в SQLite нет, но писатель на
    файл один — атомарность claim даёт BEGIN IMMEDIATE + UPDATE по
    подзапросу. Семантика интерфейса та же.

Рестарт воркера посреди раунда (contour_integration §5): строка остаётся
залоченной (locked_by/locked_at); reclaim_stale() возвращает протухшие
'in-flight' джобы в очередь — незакоммиченный раунд повторится идемпотентно.
"""

from __future__ import annotations
import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

# Статусы (contour_integration.md §2).
QUEUED = "queued"
GENERATING = "generating"
VALIDATING = "validating"
CRITIC = "critic"
AWAITING_HUMAN = "awaiting_human"
APPROVED = "approved"
REJECTED = "rejected"
ESCALATED = "escalated"
FAILED = "failed"

IN_FLIGHT = (GENERATING, VALIDATING, CRITIC)      # держатся воркером
TERMINAL = (APPROVED, REJECTED, ESCALATED, FAILED)

_JSON_FIELDS = ("constraints", "rounds", "result_graph", "result_probe", "critic")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row) -> dict:
    job = dict(row)
    for f in _JSON_FIELDS:
        if job.get(f) is not None:
            try:
                job[f] = json.loads(job[f])
            except (TypeError, json.JSONDecodeError):
                pass
    return job


class JobQueue(ABC):
    """Очередь джоб контура поверх таблицы contour_jobs."""

    @abstractmethod
    def enqueue(self, created_by: str, subject_id: int, description: str,
                constraints: Optional[dict] = None) -> str:
        """Создать джобу (status=queued). created_by — логин-строка (X-User-Id).
        Возвращает job_id (uuid)."""

    @abstractmethod
    def claim(self, worker_id: str) -> Optional[dict]:
        """Забрать одну queued-джобу (status→generating, лок за worker_id).
        None — очередь пуста. Конкурентные воркеры не получают одну строку."""

    @abstractmethod
    def get(self, job_id: str) -> Optional[dict]:
        """Джоба по id (JSON-поля распарсены) или None."""

    @abstractmethod
    def update(self, job_id: str, **fields: Any) -> None:
        """Обновить поля джобы одной транзакцией (dict/list сериализуются)."""

    @abstractmethod
    def list_for_user(self, user_id: str, role: str) -> list[dict]:
        """Джобы, видимые пользователю: свои; admin видит все
        (contour_integration §4)."""

    @abstractmethod
    def reclaim_stale(self, older_than_s: float) -> int:
        """Вернуть в очередь in-flight джобы с протухшим locked_at."""


class SqliteJobQueue(JobQueue):
    """Очередь на SQLite (dev/тесты). Атомарность claim — BEGIN IMMEDIATE."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def enqueue(self, created_by, subject_id, description,
                constraints=None) -> str:
        job_id = str(uuid.uuid4())
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO contour_jobs (id, created_by, subject_id, "
                " description, constraints, status, rounds, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                (job_id, created_by, subject_id, description,
                 json.dumps(constraints or {}, ensure_ascii=False),
                 QUEUED, now, now),
            )
        return job_id

    def claim(self, worker_id: str) -> Optional[dict]:
        with self.conn:
            # BEGIN IMMEDIATE берёт write-лок сразу: две конкурентные claim
            # сериализуются, подзапрос выбирает старейшую queued-строку.
            self.conn.execute("BEGIN IMMEDIATE")
            cur = self.conn.execute(
                "UPDATE contour_jobs SET status = ?, locked_by = ?, "
                " locked_at = ?, updated_at = ? "
                "WHERE id = (SELECT id FROM contour_jobs WHERE status = ? "
                "            ORDER BY created_at LIMIT 1) "
                "RETURNING *",
                (GENERATING, worker_id, _now(), _now(), QUEUED),
            )
            row = cur.fetchone()
        return _row_to_job(row) if row else None

    def get(self, job_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM contour_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row else None

    def update(self, job_id: str, **fields: Any) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            cols.append(f"{k} = ?")
            vals.append(v)
        cols.append("updated_at = ?")
        vals.append(_now())
        vals.append(job_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE contour_jobs SET {', '.join(cols)} WHERE id = ?", vals
            )

    def list_for_user(self, user_id: str, role: str) -> list[dict]:
        if role == "admin":
            rows = self.conn.execute(
                "SELECT * FROM contour_jobs ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM contour_jobs WHERE created_by = ? "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def reclaim_stale(self, older_than_s: float) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_s
        stale = []
        for row in self.conn.execute(
            "SELECT id, locked_at FROM contour_jobs WHERE status IN (?, ?, ?)",
            IN_FLIGHT,
        ).fetchall():
            try:
                ts = datetime.fromisoformat(row["locked_at"]).timestamp()
            except (TypeError, ValueError):
                ts = 0.0
            if ts < cutoff:
                stale.append(row["id"])
        with self.conn:
            for job_id in stale:
                self.conn.execute(
                    "UPDATE contour_jobs SET status = ?, locked_by = NULL, "
                    " locked_at = NULL, updated_at = ? WHERE id = ?",
                    (QUEUED, _now(), job_id),
                )
        return len(stale)


class PostgresJobQueue(JobQueue):
    """Боевая очередь: FOR UPDATE SKIP LOCKED (system_topology.md §4).

    Требует psycopg (v3). В юнит-тестах не поднимается (нет сервера) —
    интеграционный тест скипается без CONTOUR_PG_DSN; корректность SQL
    зафиксирована текстом CLAIM_SQL и общими тестами интерфейса.
    """

    # Ключевой запрос очереди — вынесен константой: это и документация,
    # и предмет теста (текст обязан содержать FOR UPDATE SKIP LOCKED).
    CLAIM_SQL = (
        "UPDATE contour_jobs SET status = %(next)s, locked_by = %(worker)s, "
        " locked_at = now(), updated_at = now() "
        "WHERE id = (SELECT id FROM contour_jobs WHERE status = %(queued)s "
        "            ORDER BY created_at LIMIT 1 "
        "            FOR UPDATE SKIP LOCKED) "
        "RETURNING *"
    )

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
        except ImportError:
            raise RuntimeError(
                "Для PostgresJobQueue нужен psycopg (pip install 'psycopg[binary]')."
            )
        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn, autocommit=False)

    def _dict_rows(self, cur) -> list[dict]:
        names = [d.name for d in cur.description]
        return [_row_to_job(dict(zip(names, r))) for r in cur.fetchall()]

    def enqueue(self, created_by, subject_id, description,
                constraints=None) -> str:
        job_id = str(uuid.uuid4())
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO contour_jobs (id, created_by, subject_id, "
                " description, constraints, status, rounds, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, '[]', now(), now())",
                (job_id, created_by, subject_id, description,
                 json.dumps(constraints or {}, ensure_ascii=False), QUEUED),
            )
        return job_id

    def claim(self, worker_id: str) -> Optional[dict]:
        with self.conn.transaction():
            cur = self.conn.execute(
                self.CLAIM_SQL,
                {"next": GENERATING, "worker": worker_id, "queued": QUEUED},
            )
            rows = self._dict_rows(cur)
        return rows[0] if rows else None

    def get(self, job_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM contour_jobs WHERE id = %s", (job_id,))
        rows = self._dict_rows(cur)
        return rows[0] if rows else None

    def update(self, job_id: str, **fields: Any) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            cols.append(f"{k} = %s")
            vals.append(v)
        cols.append("updated_at = now()")
        vals.append(job_id)
        with self.conn.transaction():
            self.conn.execute(
                f"UPDATE contour_jobs SET {', '.join(cols)} WHERE id = %s", vals
            )

    def list_for_user(self, user_id: str, role: str) -> list[dict]:
        if role == "admin":
            cur = self.conn.execute(
                "SELECT * FROM contour_jobs ORDER BY created_at DESC")
        else:
            cur = self.conn.execute(
                "SELECT * FROM contour_jobs WHERE created_by = %s "
                "ORDER BY created_at DESC", (user_id,))
        return self._dict_rows(cur)

    def reclaim_stale(self, older_than_s: float) -> int:
        with self.conn.transaction():
            cur = self.conn.execute(
                "UPDATE contour_jobs SET status = %s, locked_by = NULL, "
                " locked_at = NULL, updated_at = now() "
                "WHERE status = ANY(%s) "
                "  AND locked_at < now() - make_interval(secs => %s) "
                "RETURNING id",
                (QUEUED, list(IN_FLIGHT), older_than_s),
            )
            return len(cur.fetchall())
