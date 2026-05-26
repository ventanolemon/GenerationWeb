"""
Хранилище интерактивных сессий.

Сессия — это живой объект InteractiveTask, у которого есть состояние
(прогресс тренажёра, история ответов). Между двумя HTTP-запросами этот
объект должен где-то лежать. Решение — in-memory dict с UUID-ключами,
по одному инстансу на процесс uvicorn'а.

TTL обязательно: без него каждая брошенная сессия живёт вечно и
накапливается. 30 минут с момента последнего касания — разумный
дефолт; настраивается через env GENERATOR_SESSION_TTL_SECONDS.

Cleanup ленивый: при каждом обращении к стору проверяются и
удаляются протухшие записи. Без фоновых потоков — FastAPI и
без того многопоточный, лишние таймеры усложнят debugging.

Многопоточность: uvicorn по умолчанию async-однопоточный, но если
кто-то развернёт через gunicorn с workers > 1, нужен Lock —
от случайных гонок при удалении.
"""

from __future__ import annotations
import os
import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from core import InteractiveTask


DEFAULT_TTL_SECONDS = int(os.environ.get("GENERATOR_SESSION_TTL_SECONDS", "1800"))


@dataclass
class _Entry:
    task: InteractiveTask
    partition_id: int
    last_touched: float


class SessionStore:
    """Хранилище InteractiveTask-сессий с TTL."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._items: dict[str, _Entry] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds

    def create(self, task: InteractiveTask, partition_id: int) -> str:
        """Положить новую сессию, вернуть session_id."""
        session_id = str(uuid.uuid4())
        with self._lock:
            self._sweep_locked()
            self._items[session_id] = _Entry(
                task=task,
                partition_id=partition_id,
                last_touched=time.time(),
            )
        return session_id

    def get(self, session_id: str) -> Optional[InteractiveTask]:
        """Достать сессию. Обновляет last_touched. None — если не найдена."""
        with self._lock:
            self._sweep_locked()
            entry = self._items.get(session_id)
            if entry is None:
                return None
            entry.last_touched = time.time()
            return entry.task

    def remove(self, session_id: str) -> None:
        """Удалить сессию (например, по её завершении)."""
        with self._lock:
            self._items.pop(session_id, None)

    def stats(self) -> dict:
        """Диагностика: сколько сейчас живых сессий и какой им возраст."""
        with self._lock:
            self._sweep_locked()
            now = time.time()
            return {
                "alive": len(self._items),
                "ttl_seconds": self._ttl,
                "ages_seconds": sorted(
                    int(now - e.last_touched) for e in self._items.values()
                ),
            }

    def _sweep_locked(self) -> None:
        """Удалить протухшие записи. Вызывается только под self._lock."""
        if not self._items:
            return
        now = time.time()
        expired = [
            sid for sid, entry in self._items.items()
            if now - entry.last_touched > self._ttl
        ]
        for sid in expired:
            self._items.pop(sid, None)
