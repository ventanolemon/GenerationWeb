"""
Состояние времени выполнения: интерактивные сессии и статистика слов.

Не предметная область, а то, что сервису нужно пережить перезапуск и
работу за балансировщиком.
"""

from __future__ import annotations
import json
import time
from typing import List, Optional


class RuntimeMixin:
    """Сессии тренажёров и накопленная статистика."""
    # ---------- Интерактивные сессии ----------
    #
    # Состояние живого тренажёра между HTTP-ходами. Лежит в БД, а не в
    # памяти процесса: иначе сервис не переживает ни балансировщик (второй
    # ход придёт в другой процесс), ни собственный перезапуск. Формат
    # `state` принадлежит типу задания (`InteractiveTask.state()`) —
    # Repository его не разбирает, а хранит.

    def save_interactive_session(
        self, session_id: str, partition_id: int,
        user_id: Optional[str], state: dict,
    ) -> None:
        """Создать или обновить сессию (upsert по session_id)."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO interactive_sessions "
                "(session_id, partition_id, user_id, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "  state = excluded.state, updated_at = excluded.updated_at",
                (session_id, partition_id, user_id,
                 json.dumps(state or {}, ensure_ascii=False), now, now),
            )

    def load_interactive_session(self, session_id: str) -> Optional[dict]:
        """`{partition_id, user_id, state, updated_at}` или None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT partition_id, user_id, state, updated_at "
                "FROM interactive_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            state = json.loads(row[2] or "{}")
        except json.JSONDecodeError:
            # Битую запись лечим как отсутствующую: пересобрать сессию из
            # мусора нельзя, а ронять ход пользователя из-за этого незачем.
            state = {}
        return {"partition_id": row[0], "user_id": row[1],
                "state": state if isinstance(state, dict) else {},
                "updated_at": row[3] or 0.0}

    def delete_interactive_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM interactive_sessions WHERE session_id = ?",
                (session_id,),
            )

    def sweep_interactive_sessions(self, older_than: float) -> int:
        """Удалить сессии, не тронутые дольше TTL. Возвращает число удалённых."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM interactive_sessions WHERE updated_at < ?",
                (older_than,),
            )
            return cur.rowcount

    def count_interactive_sessions(self) -> int:
        with self._connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM interactive_sessions").fetchone()[0])

    # ---------- WordStats ----------

    def ensure_word_stats_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS WordStats ("
                "  user_id TEXT NOT NULL,"
                "  term TEXT NOT NULL,"
                "  times_shown INTEGER NOT NULL DEFAULT 0,"
                "  times_correct INTEGER NOT NULL DEFAULT 0,"
                "  times_wrong INTEGER NOT NULL DEFAULT 0,"
                "  last_seen REAL NOT NULL DEFAULT 0,"
                "  PRIMARY KEY (user_id, term)"
                ")"
            )

    def fetch_word_stats(self, user_id: str, terms: List[str]) -> dict:
        from .word_stats import WordStat

        if not terms:
            return {}
        out: dict[str, WordStat] = {}
        chunk_size = 500
        with self._connect() as conn:
            for i in range(0, len(terms), chunk_size):
                chunk = terms[i:i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT term, times_shown, times_correct, times_wrong, "
                    f"       last_seen "
                    f"FROM WordStats "
                    f"WHERE user_id = ? AND term IN ({placeholders})",
                    (user_id, *chunk),
                ).fetchall()
                for r in rows:
                    out[r[0]] = WordStat(
                        term=r[0],
                        times_shown=r[1],
                        times_correct=r[2],
                        times_wrong=r[3],
                        last_seen=r[4],
                    )
        return out

    def upsert_word_stat(
        self, user_id: str, term: str, correct: bool, now: float
    ) -> None:
        delta_correct = 1 if correct else 0
        delta_wrong = 0 if correct else 1
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO WordStats "
                "(user_id, term, times_shown, times_correct, times_wrong, last_seen) "
                "VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(user_id, term) DO UPDATE SET "
                "  times_shown = times_shown + 1, "
                "  times_correct = times_correct + ?, "
                "  times_wrong = times_wrong + ?, "
                "  last_seen = ?",
                (user_id, term, delta_correct, delta_wrong, now,
                 delta_correct, delta_wrong, now),
            )

    def fetch_all_word_stats(self, user_id: str) -> list:
        from .word_stats import WordStat

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT term, times_shown, times_correct, times_wrong, last_seen "
                "FROM WordStats WHERE user_id = ? "
                "ORDER BY last_seen DESC",
                (user_id,),
            ).fetchall()
        return [
            WordStat(
                term=r[0],
                times_shown=r[1],
                times_correct=r[2],
                times_wrong=r[3],
                last_seen=r[4],
            )
            for r in rows
        ]
