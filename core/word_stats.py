"""
WordStats — межсессионная статистика по словам.

Хранит для каждой пары (user_id, term) счётчики times_shown, times_correct,
times_wrong и метку last_seen. На основе этой статистики словарный тренажёр
строит spaced-repetition-каркас: давно не виденные и часто ошибочные слова
получают приоритет в новой сессии.

Стратегия хранения:
  * Авторизованные пользователи — SQLite-таблица WordStats через Repository.
  * Гости — общая in-memory таблица (живёт пока работает приложение,
    сбрасывается при перезапуске).

API:
  WordStatsStore(repo)         — конструктор; гарантирует наличие таблицы.
  store.fetch(user_id, terms)  — dict[term, WordStat] для перечисленных слов.
  store.record(user_id, term, correct: bool) — обновить статистику.

user_id == None или пустая строка → гостевой режим (in-memory).
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Iterable


_GUEST_BUCKET = "__guest__"


@dataclass
class WordStat:
    """Снимок статистики по одному слову."""
    term: str
    times_shown: int = 0
    times_correct: int = 0
    times_wrong: int = 0
    last_seen: float = 0.0   # unix-timestamp; 0.0 = «не видели»


class WordStatsStore:
    """Гибридное хранилище: SQLite для пользователей, in-memory для гостей."""

    def __init__(self, repository) -> None:
        self._repo = repository
        # Гостевая статистика — общая на сессию приложения.
        # Ключ — _GUEST_BUCKET, чтобы при необходимости расширить
        # (например, разделять по типу анонимного запуска).
        self._guest: dict[str, dict[str, WordStat]] = {_GUEST_BUCKET: {}}
        try:
            self._repo.ensure_word_stats_table()
        except Exception:
            # Если БД недоступна — продолжаем работать только в in-memory режиме.
            # Поведение для авторизованных пользователей в этом случае
            # деградирует до гостевого, но приложение не падает.
            pass

    # ---------- Чтение ----------

    def fetch(
        self, user_id: str | None, terms: Iterable[str]
    ) -> dict[str, WordStat]:
        """
        Получить статистику для заданного списка слов. Для отсутствующих в
        хранилище — вернётся «пустой» WordStat (все счётчики = 0).
        """
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

    # ---------- Запись ----------

    def record(
        self, user_id: str | None, term: str, correct: bool,
        now: float | None = None,
    ) -> None:
        """Зафиксировать один показ слова и его исход."""
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
            # При сбое записи в БД деградируем в гостевой режим для этого слова,
            # чтобы приоритизация в текущей сессии всё равно работала.
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
        """
        Все слова со статистикой для пользователя. Для гостей — содержимое
        in-memory bucket; для авторизованных — запрос к БД, отсортированный
        по last_seen DESC.
        """
        if self._is_guest(user_id):
            stats = list(self._guest[_GUEST_BUCKET].values())
            stats.sort(key=lambda s: s.last_seen, reverse=True)
            return stats
        try:
            return self._repo.fetch_all_word_stats(user_id)
        except Exception:
            return []

    # ---------- Вспомогательное ----------

    @staticmethod
    def _is_guest(user_id: str | None) -> bool:
        return user_id is None or user_id == ""
