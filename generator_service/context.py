"""
ContextVar для user_id текущего HTTP-запроса.

Устанавливается в роутере /generate перед вызовом generator.generate(),
чтобы WordsTrainerGenerator.user_id_provider() вернул нужный user_id
без глобального состояния.

ContextVar является корутинобезопасным и потокобезопасным:
каждый запрос FastAPI (sync-роуты работают в thread pool) видит
только своё значение, установленное в начале обработки запроса.
"""

from __future__ import annotations
from contextvars import ContextVar
from typing import Optional

current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id", default=None
)
