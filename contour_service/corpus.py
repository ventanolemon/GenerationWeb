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

    # ---------- Курация (training_plan.md §1) ----------
    #
    # Витрина куратора корпуса: список с фильтрами, детальная запись, разметка
    # «золотой эталон / исключить / коммент». curation живёт отдельной таблицей
    # corpus_curation (LEFT JOIN); отсутствие строки = 'auto' (не размечено).

    # Что показываем по умолчанию — обучающие записи (не сырые escalation-логи).
    TRAINING_KINDS = ("generate", "repair")

    def _q(self, sql: str, args: tuple = ()):
        """Выполнить SELECT независимо от бэкенда. SQL пишем с '?';
        для Postgres конвертируем в '%s' (в наших запросах '?' не встречается
        в строковых литералах). Доступ к полям — по индексу: работает и для
        sqlite3.Row, и для tuple'ов DB-API Postgres."""
        if self._sqlite:
            return self.conn.execute(sql, args).fetchall()
        cur = self.conn.execute(sql.replace("?", "%s"), args)
        return cur.fetchall()

    @staticmethod
    def _summary_fields(rec: dict) -> dict:
        """Плоские поля записи для таблицы/детали куратора."""
        prov = rec.get("provenance") or {}
        validator = prov.get("validator") or {}
        critic = prov.get("critic") or {}
        probe_flags = prov.get("probe_flags") or []
        failures = [c for c in (critic.get("failures") or []) if c]
        codes = sorted(set(probe_flags) | set(failures))
        human = prov.get("human") or {}
        return {
            "description": (rec.get("input") or {}).get("description", ""),
            "tags": rec.get("tags") or [],
            "validator_passed": bool(validator.get("passed")),
            "seeds": len(validator.get("seeds") or []),
            "verdict": critic.get("verdict"),
            "confidence": critic.get("confidence"),
            "codes": codes,
            "human_approved": bool(human.get("approved")),
            "model": prov.get("model", ""),
        }

    def list_curated(self, *, curation: Optional[str] = None,
                     kinds: Optional[tuple] = None,
                     limit: int = 500) -> dict:
        """Список обучающих записей + разметка курации, свёрнутые в поля для
        таблицы. Фильтр по curation ('auto'|'gold'|'excluded') применяем в
        Python (auto = нет строки в corpus_curation). MVP-оговорка: грузим
        пачкой и фильтруем в памяти — при академическом масштабе достаточно."""
        kinds = kinds or self.TRAINING_KINDS
        ph = ",".join("?" * len(kinds))
        rows = self._q(
            f"SELECT r.id, r.kind, r.created_at, r.record, "
            f"       c.curation, c.comment, c.curated_by, c.curated_at "
            f"FROM corpus_records r "
            f"LEFT JOIN corpus_curation c ON c.record_id = r.id "
            f"WHERE r.kind IN ({ph}) "
            f"ORDER BY r.created_at DESC LIMIT ?",
            (*kinds, int(limit)),
        )
        out = []
        for r in rows:
            rec = r[3] if isinstance(r[3], dict) else json.loads(r[3])
            cur_state = r[4] or "auto"
            if curation and cur_state != curation:
                continue
            out.append({
                "id": r[0], "kind": r[1], "created_at": r[2],
                "curation": cur_state, "comment": r[5] or "",
                "curated_by": r[6], "curated_at": r[7],
                **self._summary_fields(rec),
            })
        return {"records": out, "total": len(out)}

    def get_curated(self, record_id: str) -> Optional[dict]:
        """Полная запись + её курация. None — записи нет."""
        rows = self._q(
            "SELECT r.id, r.kind, r.created_at, r.record, "
            "       c.curation, c.comment, c.curated_by, c.curated_at "
            "FROM corpus_records r "
            "LEFT JOIN corpus_curation c ON c.record_id = r.id "
            "WHERE r.id = ?",
            (record_id,),
        )
        if not rows:
            return None
        r = rows[0]
        rec = r[3] if isinstance(r[3], dict) else json.loads(r[3])
        return {
            "id": r[0], "kind": r[1], "created_at": r[2],
            "curation": r[4] or "auto", "comment": r[5] or "",
            "curated_by": r[6], "curated_at": r[7],
            "record": rec,
            **self._summary_fields(rec),
        }

    def set_curation(self, record_id: str, curation: str, *,
                     comment: str = "", curator: str = "") -> bool:
        """Разметить запись (upsert corpus_curation). False — записи нет."""
        if curation not in ("auto", "gold", "excluded"):
            raise ValueError(f"недопустимая курация {curation!r}")
        exists = self._q("SELECT 1 FROM corpus_records WHERE id = ?", (record_id,))
        if not exists:
            return False
        now = _now()
        if self._sqlite:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO corpus_curation "
                    "(record_id, curation, comment, curated_by, curated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(record_id) DO UPDATE SET "
                    "curation=excluded.curation, comment=excluded.comment, "
                    "curated_by=excluded.curated_by, curated_at=excluded.curated_at",
                    (record_id, curation, comment, curator, now))
        else:
            with self.conn.transaction():
                self.conn.execute(
                    "INSERT INTO corpus_curation "
                    "(record_id, curation, comment, curated_by, curated_at) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT(record_id) DO UPDATE SET "
                    "curation=EXCLUDED.curation, comment=EXCLUDED.comment, "
                    "curated_by=EXCLUDED.curated_by, curated_at=EXCLUDED.curated_at",
                    (record_id, curation, comment, curator, now))
        return True

    def curation_summary(self) -> dict:
        """Сводка для верхней панели: счётчики по виду/курации + распределение
        провалов по кодам таксономии (probe_flags + provenance.critic)."""
        rows = self._q(
            "SELECT r.kind, r.record, c.curation "
            "FROM corpus_records r "
            "LEFT JOIN corpus_curation c ON c.record_id = r.id "
            "WHERE r.kind IN ('generate', 'repair')",
        )
        gold = excluded = auto = generate = repair = 0
        code_counts: dict[str, int] = {}
        for r in rows:
            kind = r[0]
            rec = r[1] if isinstance(r[1], dict) else json.loads(r[1])
            state = r[2] or "auto"
            if kind == "generate":
                generate += 1
            elif kind == "repair":
                repair += 1
            if state == "gold":
                gold += 1
            elif state == "excluded":
                excluded += 1
            else:
                auto += 1
            for code in self._summary_fields(rec)["codes"]:
                code_counts[code] = code_counts.get(code, 0) + 1
        distribution = sorted(
            ({"code": k, "count": v} for k, v in code_counts.items()),
            key=lambda d: d["count"], reverse=True)
        return {
            "total": generate + repair,
            "generate": generate,
            "repair": repair,
            "escalations": self.count("escalation"),
            "gold": gold,
            "excluded": excluded,
            "auto": auto,
            "code_distribution": distribution,
        }
