"""
Хранилище интерактивных сессий.

Сессия — это живой объект InteractiveTask, у которого есть состояние
(прогресс тренажёра, история ответов). Между двумя HTTP-запросами этот
объект должен где-то лежать.

**Два уровня, а не один.** В памяти процесса — кеш живых объектов (быстрый
путь: подряд идущие ходы одного пользователя почти всегда попадают в тот
же процесс). В БД — снимок состояния (`InteractiveTask.state()`), с
которого сессию можно пересобрать где угодно. Раньше уровень был один,
in-memory, и это ограничивало развёртывание: за балансировщиком второй ход
приходил в другой процесс и не находил сессию, а перезапуск сервиса ронял
все активные тренажёры. Теперь промах кеша — не «сессия истекла», а повод
поднять её из БД.

Пересборка: по `partition_id` тем же генератором, что создал сессию, затем
`restore()` возвращает прогресс. Поэтому стору нужна фабрика
`task_factory(partition_id, user_id)` — сам он про реестр генераторов не
знает и знать не должен.

Тип задания вправе не уметь сниматься: `state()` по умолчанию отдаёт None.
Такая сессия живёт только в памяти, как и прежде, — деградация тихая и
осознанная, а не отказ.

TTL обязателен: без него брошенная сессия живёт вечно. 30 минут с момента
последнего касания; настраивается через GENERATOR_SESSION_TTL_SECONDS.
Cleanup ленивый — при обращении к стору, без фоновых потоков; чистятся оба
уровня, иначе БД копила бы мусор, невидимый для памяти.

Многопоточность: uvicorn async-однопоточный, но при gunicorn с workers > 1
нужен Lock — от гонок при удалении.
"""

from __future__ import annotations
import logging
import os
import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Optional

from core import InteractiveTask

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = int(os.environ.get("GENERATOR_SESSION_TTL_SECONDS", "1800"))

# partition_id, user_id → свежесобранное задание (или None, если генератора
# для партиции больше нет).
TaskFactory = Callable[[int, Optional[str]], Optional[InteractiveTask]]


@dataclass
class _Entry:
    task: InteractiveTask
    partition_id: int
    user_id: Optional[str]
    last_touched: float


class SessionStore:
    """Хранилище InteractiveTask-сессий с TTL и опциональным персистом."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        *,
        repo=None,
        task_factory: Optional[TaskFactory] = None,
    ):
        self._items: dict[str, _Entry] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds
        # repo и task_factory нужны ОБА: без первого некуда писать, без
        # второго нечем пересобрать. Отсутствие любого = чистый in-memory
        # режим (тесты, локальный запуск) — не ошибка.
        self._repo = repo
        self._task_factory = task_factory
        self._last_db_sweep = 0.0

    @property
    def durable(self) -> bool:
        return self._repo is not None and self._task_factory is not None

    # ---------- Запись ----------

    def create(self, task: InteractiveTask, partition_id: int,
               user_id: Optional[str] = None) -> str:
        """Положить новую сессию, вернуть session_id."""
        session_id = str(uuid.uuid4())
        with self._lock:
            self._sweep_locked()
            self._items[session_id] = _Entry(
                task=task,
                partition_id=partition_id,
                user_id=user_id,
                last_touched=time.time(),
            )
        self.save(session_id)
        return session_id

    def save(self, session_id: str) -> bool:
        """
        Сохранить текущее состояние сессии. Зовётся после каждого хода:
        снимок, отставший на ход, вернул бы пользователя назад при
        переезде между процессами.

        Возвращает True, если снимок реально записан.
        """
        if not self.durable:
            return False
        with self._lock:
            entry = self._items.get(session_id)
        if entry is None:
            return False
        try:
            state = entry.task.state()
        except Exception:
            logger.exception("state() сессии %s упал", session_id)
            return False
        if state is None:
            return False            # тип задания не умеет — это законно
        try:
            self._repo.save_interactive_session(
                session_id, entry.partition_id, entry.user_id, state)
            return True
        except Exception:
            # Персист — улучшение, а не условие работы: сессия в памяти
            # жива, и ронять из-за БД текущий ход пользователя незачем.
            logger.exception("не удалось сохранить сессию %s", session_id)
            return False

    # ---------- Чтение ----------

    def get(self, session_id: str) -> Optional[InteractiveTask]:
        """Достать сессию. Обновляет last_touched. None — если не найдена."""
        with self._lock:
            self._sweep_locked()
            entry = self._items.get(session_id)
            if entry is not None:
                entry.last_touched = time.time()
                return entry.task
        return self._revive(session_id)

    def _revive(self, session_id: str) -> Optional[InteractiveTask]:
        """Поднять сессию из БД: пересобрать задание и вернуть ему прогресс."""
        if not self.durable:
            return None
        row = self._repo.load_interactive_session(session_id)
        if row is None:
            return None
        if time.time() - (row["updated_at"] or 0.0) > self._ttl:
            # Протухла: чистим сразу, чтобы не поднимать её снова.
            self._repo.delete_interactive_session(session_id)
            return None
        try:
            task = self._task_factory(row["partition_id"], row["user_id"])
        except Exception:
            logger.exception("пересборка сессии %s не удалась", session_id)
            return None
        if task is None:
            # Генератора для партиции больше нет (раздел удалили) — сессию
            # не воскресить, и держать её запись смысла нет.
            self._repo.delete_interactive_session(session_id)
            return None
        try:
            task.restore(row["state"])
        except Exception:
            logger.exception("restore() сессии %s не удался", session_id)
            return None
        with self._lock:
            self._items[session_id] = _Entry(
                task=task, partition_id=row["partition_id"],
                user_id=row["user_id"], last_touched=time.time(),
            )
        return task

    # ---------- Удаление ----------

    def remove(self, session_id: str) -> None:
        """Удалить сессию (например, по её завершении) с обоих уровней."""
        with self._lock:
            self._items.pop(session_id, None)
        if self.durable:
            try:
                self._repo.delete_interactive_session(session_id)
            except Exception:
                logger.exception("не удалось удалить сессию %s", session_id)

    # ---------- Диагностика ----------

    def stats(self) -> dict:
        """Сколько сейчас живых сессий и какой им возраст."""
        with self._lock:
            self._sweep_locked()
            now = time.time()
            out = {
                "alive": len(self._items),
                "ttl_seconds": self._ttl,
                "durable": self.durable,
                "ages_seconds": sorted(
                    int(now - e.last_touched) for e in self._items.values()
                ),
            }
        if self.durable:
            try:
                out["stored"] = self._repo.count_interactive_sessions()
            except Exception:
                logger.exception("не удалось посчитать сохранённые сессии")
        return out

    def _sweep_locked(self) -> None:
        """Удалить протухшие записи. Вызывается только под self._lock."""
        now = time.time()
        expired = [
            sid for sid, entry in self._items.items()
            if now - entry.last_touched > self._ttl
        ]
        for sid in expired:
            self._items.pop(sid, None)
        if not self.durable:
            return
        # Хранилище чистится независимо от памяти: сессию мог создать другой
        # процесс, и в этом dict её никогда не было. Но не на каждом
        # обращении — это DELETE на каждый ход пользователя; раз в TTL/10
        # достаточно, протухшую запись всё равно отсекает проверка в _revive.
        if now - self._last_db_sweep < max(30.0, self._ttl / 10):
            return
        self._last_db_sweep = now
        try:
            self._repo.sweep_interactive_sessions(now - self._ttl)
        except Exception:
            logger.exception("вычистка сохранённых сессий не удалась")
