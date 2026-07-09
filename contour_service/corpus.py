"""
Персист корпуса: corpus_records (rbac_and_data_model.md §5 — БД, не файлы).

Записи рождаются в событиях петли (closed_loop_contract.md §5):
  - успешный repair-раунд      → kind="repair"   (сразу, не ждёт человека)
  - принято человеком (S6)     → kind="generate" (human.approved=true)
  - эскалация / отклонение     → kind="escalation" (сырой лог, не для обучения)

generate/repair-записи — ДОСЛОВНО по training_example_schema.json (это
инвариант корпуса: target_graph в рантайм-формате GraphSpec.to_dict()).
graph_hash пишется при вставке; дедуп — UNIQUE-индекс (kind, graph_hash):
повторная вставка того же графа тихо игнорируется, а не чистится потом.

Инвариант №3 контракта («ни одна запись корпуса не создаётся без
probe-отчёта») зашит в сигнатуры: write_generate/write_repair ТРЕБУЮТ probe.
"""

from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from .graph_hash import canonical_graph_hash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CorpusStore:
    """Запись/чтение corpus_records поверх DB-API соединения."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self._sqlite = isinstance(conn, sqlite3.Connection)

    # ---------- Вставка ----------

    def _insert(self, job_id: str, kind: str, record: dict,
                graph_hash: Optional[str]) -> Optional[str]:
        """INSERT с дедупом по (kind, graph_hash). None — дубль (пропущен)."""
        rec_id = str(uuid.uuid4())
        payload = json.dumps(record, ensure_ascii=False)
        if self._sqlite:
            sql = ("INSERT OR IGNORE INTO corpus_records "
                   "(id, job_id, kind, record, graph_hash, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?)")
            with self.conn:
                cur = self.conn.execute(
                    sql, (rec_id, job_id, kind, payload, graph_hash, _now()))
            return rec_id if cur.rowcount else None
        sql = ("INSERT INTO corpus_records "
               "(id, job_id, kind, record, graph_hash, created_at) "
               "VALUES (%s, %s, %s, %s, %s, now()) "
               "ON CONFLICT DO NOTHING")
        with self.conn.transaction():
            cur = self.conn.execute(
                sql, (rec_id, job_id, kind, payload, graph_hash))
            return rec_id if cur.rowcount else None

    @staticmethod
    def _provenance(source: str, model: str, catalog_version: str,
                    engine_commit: str, probe: dict,
                    critic: Optional[dict]) -> dict:
        seeds = probe.get("seeds") or []
        agg = probe.get("aggregates") or {}
        prov = {
            "source": source,
            "model": model,
            "created_at": _now(),
            "catalog_version": catalog_version,
            "engine_commit": engine_commit,
            "validator": {
                "passed": agg.get("runs_ok", 0) == agg.get("runs_total", 0),
                "seeds": seeds,
                "attempts_max": agg.get("attempts_max", 0),
            },
            "probe_flags": sorted({f["code"] for f in probe.get("flags", [])}),
        }
        if critic:
            prov["critic"] = {
                "verdict": critic.get("verdict"),
                "failures": [f.get("code") for f in critic.get("failures", [])],
                "confidence": critic.get("confidence"),
                "model": critic.get("model", ""),
            }
        return prov

    def write_repair(self, job_id: str, description: str,
                     prior_graph: dict, errors: list[str],
                     target_graph: dict, probe: dict, *,
                     catalog_version: str, engine_commit: str,
                     model: str = "", fewshot_ids: Optional[list[str]] = None,
                     tags: Optional[list[str]] = None) -> Optional[str]:
        """Успешный repair-раунд: битый граф + ДОСЛОВНЫЕ ошибки → починенный.
        Probe обязателен (инвариант №3). Возвращает id записи или None (дубль)."""
        gh = canonical_graph_hash(target_graph)
        record = {
            "id": f"rep-{uuid.uuid4().hex[:12]}",
            "schema_version": 1,
            "kind": "repair",
            "input": {
                "description": description,
                "prior_graph": prior_graph,
                "errors": list(errors),
                **({"fewshot_ids": fewshot_ids} if fewshot_ids else {}),
            },
            "target_graph": target_graph,
            "provenance": self._provenance(
                "loop_log", model, catalog_version, engine_commit, probe, None),
            "tags": tags or [],
        }
        return self._insert(job_id, "repair", record, gh)

    def write_generate(self, job_id: str, description: str,
                       constraints: Optional[dict], target_graph: dict,
                       probe: dict, critic: Optional[dict], *,
                       catalog_version: str, engine_commit: str,
                       model: str = "", fewshot_ids: Optional[list[str]] = None,
                       approved: bool = True, note: str = "",
                       tags: Optional[list[str]] = None) -> Optional[str]:
        """Принятая генерация (S6 approve). Probe обязателен (инвариант №3)."""
        gh = canonical_graph_hash(target_graph)
        record = {
            "id": f"gen-{uuid.uuid4().hex[:12]}",
            "schema_version": 1,
            "kind": "generate",
            "input": {
                "description": description,
                **({"constraints": constraints} if constraints else {}),
                **({"fewshot_ids": fewshot_ids} if fewshot_ids else {}),
            },
            "target_graph": target_graph,
            "provenance": {
                **self._provenance("loop_log", model, catalog_version,
                                   engine_commit, probe, critic),
                "human": {"approved": approved, **({"note": note} if note else {})},
            },
            "tags": tags or [],
        }
        return self._insert(job_id, "generate", record, gh)

    def write_escalation(self, job_id: str, description: str, reason: str,
                         rounds: list[dict], *, catalog_version: str,
                         engine_commit: str) -> Optional[str]:
        """Эскалация/отклонение: лог целиком. Не для обучения напрямую —
        источник негативов и статистики тем (частота эскалаций по темам =
        метрика качества заземления)."""
        record = {
            "kind": "escalation",
            "description": description,
            "reason": reason,
            "rounds": rounds,
            "catalog_version": catalog_version,
            "engine_commit": engine_commit,
            "created_at": _now(),
        }
        return self._insert(job_id, "escalation", record, None)

    # ---------- Чтение (few-shot из накопленного корпуса) ----------

    def approved_generate_records(self, limit: int = 200) -> list[dict]:
        """Принятые человеком generate-записи (для few-shot retrieval S0)."""
        if self._sqlite:
            rows = self.conn.execute(
                "SELECT id, record FROM corpus_records WHERE kind = 'generate' "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            items = [{"id": r["id"], "record": json.loads(r["record"])}
                     for r in rows]
        else:
            cur = self.conn.execute(
                "SELECT id, record FROM corpus_records WHERE kind = 'generate' "
                "ORDER BY created_at DESC LIMIT %s", (limit,))
            items = [{"id": r[0], "record": json.loads(r[1])
                      if isinstance(r[1], str) else r[1]}
                     for r in cur.fetchall()]
        return [
            it for it in items
            if ((it["record"].get("provenance") or {}).get("human") or {})
            .get("approved")
        ]

    def count(self, kind: Optional[str] = None) -> int:
        q = "SELECT COUNT(*) FROM corpus_records"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?" if self._sqlite else " WHERE kind = %s"
            args = (kind,)
        if self._sqlite:
            return int(self.conn.execute(q, args).fetchone()[0])
        cur = self.conn.execute(q, args)
        return int(cur.fetchone()[0])
