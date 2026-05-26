"""
WordStats — межсессионная статистика по словам. Без изменений.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Iterable


_GUEST_BUCKET = "__guest__"


@dataclass
class WordStat:
    term: str
    times_shown: int = 0
    times_correct: int = 0
    times_wrong: int = 0
    last_seen: float = 0.0


class WordStatsStore:
    def __init__(self, repository) -> None:
        self._repo = repository
        self._guest: dict[str, dict[str, WordStat]] = {_GUEST_BUCKET: {}}
        try:
            self._repo.ensure_word_stats_table()
        except Exception:
            pass

    def fetch(self, user_id: str | None, terms: Iterable[str]) -> dict[str, WordStat]:
        term_list = list(terms)
        if not term_list:
            return {}
        if self._is_guest(user_id):
            bucket = self._guest[_GUEST_BUCKET]
            return {t: bucket.get(t, WordStat(term=t)) for t in term_list}
        try:
            existing = self._repo.fetch_word_stats(user_id, term_list)
        except Exception:
            existing = {}
        return {t: existing.get(t, WordStat(term=t)) for t in term_list}

    def record(self, user_id: str | None, term: str, correct: bool,
               now: float | None = None) -> None:
        ts = time.time() if now is None else now
        if self._is_guest(user_id):
            bucket = self._guest[_GUEST_BUCKET]
            stat = bucket.get(term)
            if stat is None:
                stat = WordStat(term=term)
                bucket[term] = stat
            stat.times_shown += 1
            if correct:
                stat.times_correct += 1
            else:
                stat.times_wrong += 1
            stat.last_seen = ts
            return
        try:
            self._repo.upsert_word_stat(user_id, term, correct, ts)
        except Exception:
            bucket = self._guest[_GUEST_BUCKET]
            stat = bucket.get(term, WordStat(term=term))
            stat.times_shown += 1
            if correct:
                stat.times_correct += 1
            else:
                stat.times_wrong += 1
            stat.last_seen = ts
            bucket[term] = stat

    def fetch_all(self, user_id: str | None) -> list[WordStat]:
        if self._is_guest(user_id):
            stats = list(self._guest[_GUEST_BUCKET].values())
            stats.sort(key=lambda s: s.last_seen, reverse=True)
            return stats
        try:
            return self._repo.fetch_all_word_stats(user_id)
        except Exception:
            return []

    @staticmethod
    def _is_guest(user_id: str | None) -> bool:
        return user_id is None or user_id == ""
