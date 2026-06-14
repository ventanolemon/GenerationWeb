"""
GET /stats — сводка и история словарного тренажёра для окна профиля.

Повторяет логику десктопного StatsWindow: сводные счётчики + список слов
с переводами, точностью и временем последнего показа. Работает и для
авторизованных (данные из SQLite), и для гостей (in-memory bucket в
WordStatsStore) — источник определяется по user_id.

Переводы (term → translation) собираются из всех словарей WORDS_DIR один
раз и кэшируются в app.state (словари в рантайме не меняются).
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from const import WORDS_DIR

router = APIRouter(prefix="/stats", tags=["stats"])


def _load_translations(request: Request) -> dict[str, str]:
    """Сводный term→translation по всем словарям. Кэшируется в app.state."""
    cached = getattr(request.app.state, "translations", None)
    if cached is not None:
        return cached

    out: dict[str, str] = {}
    if WORDS_DIR.exists():
        from exercises.english.generators import (
            WordsTrainerGenerator, _read_json_lenient, _detect_kind,
        )
        for path in sorted(WORDS_DIR.glob("*.json")):
            try:
                if _detect_kind(path) != "words":
                    continue
                data = _read_json_lenient(path)
                out.update(WordsTrainerGenerator._flatten_words(data))
            except Exception:
                continue

    request.app.state.translations = out
    return out


@router.get("")
def get_stats(request: Request, user_id: Optional[str] = None) -> dict:
    store = getattr(request.app.state, "stats_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Statistics store unavailable")

    stats = store.fetch_all(user_id)
    translations = _load_translations(request)

    total_terms = len(stats)
    total_shown = sum(s.times_shown for s in stats)
    total_correct = sum(s.times_correct for s in stats)
    total_wrong = sum(s.times_wrong for s in stats)
    denom = total_correct + total_wrong
    accuracy = (total_correct / denom) if denom > 0 else 0.0

    words = []
    for s in stats:
        d = s.times_correct + s.times_wrong
        words.append({
            "term": s.term,
            "translation": translations.get(s.term, ""),
            "times_shown": s.times_shown,
            "times_correct": s.times_correct,
            "times_wrong": s.times_wrong,
            "accuracy": (s.times_correct / d) if d > 0 else None,
            "last_seen": s.last_seen,
        })

    return {
        "is_guest": user_id is None or user_id == "",
        "summary": {
            "total_terms": total_terms,
            "total_shown": total_shown,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "accuracy": accuracy,
        },
        "words": words,
    }
