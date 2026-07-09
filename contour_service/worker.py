"""
Воркер контура: claim джобы из очереди → петля S0–S5 → персист итога.

Смена статуса и персист артефактов раунда пишутся в contour_jobs по ходу
петли (on_status/on_round); итоговая запись (rounds/result_*/status) —
одним update. Отказ провайдера → status=failed, бюджет V не тронут
(contour_integration §5).

Запуск отдельным процессом:  python -m contour_service.worker
(в main.py тот же цикл поднимается фоновой asyncio-задачей).
"""

from __future__ import annotations
import logging
import traceback
import uuid

from .loop import LoopDeps, run_pipeline
from .providers import ProviderError
from .queue import FAILED, JobQueue

logger = logging.getLogger("contour_service.worker")


def process_one(queue: JobQueue, deps: LoopDeps,
                worker_id: str = "") -> bool:
    """Обработать одну джобу. False — очередь пуста (можно спать)."""
    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    job = queue.claim(worker_id)
    if job is None:
        return False
    job_id = job["id"]
    logger.info("job %s: claimed by %s", job_id, worker_id)

    rounds_seen: list[dict] = []

    def on_status(status: str) -> None:
        queue.update(job_id, status=status)

    def on_round(rnd: dict) -> None:
        # Каждый завершённый раунд — сразу в rounds (история для экрана S6).
        rounds_seen.append(rnd)
        queue.update(job_id, rounds=rounds_seen)

    try:
        outcome = run_pipeline(job, deps, on_status=on_status, on_round=on_round)
    except ProviderError as e:
        # Недоступность LLM — не ошибка графа: failed без расхода бюджетов.
        logger.warning("job %s: provider failed: %s", job_id, e)
        queue.update(job_id, status=FAILED,
                     error=f"провайдер недоступен: {e}",
                     locked_by=None, locked_at=None)
        return True
    except Exception as e:  # неожиданный сбой оркестратора — не терять джобу
        logger.error("job %s: crashed: %s\n%s", job_id, e, traceback.format_exc())
        queue.update(job_id, status=FAILED, error=f"внутренняя ошибка: {e}",
                     locked_by=None, locked_at=None)
        return True

    queue.update(
        job_id,
        status=outcome.status,
        rounds=outcome.rounds,
        result_graph=outcome.result_graph,
        result_probe=outcome.result_probe,
        critic=outcome.critic,
        error=outcome.error,
        locked_by=None, locked_at=None,
    )
    logger.info("job %s: %s", job_id, outcome.status)
    return True


def run_forever(queue: JobQueue, deps: LoopDeps,
                poll_interval_s: float = 2.0,
                stale_after_s: float = 30 * 60.0) -> None:
    """Блокирующий цикл воркера (отдельный процесс)."""
    import time
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("contour worker %s started", worker_id)
    while True:
        queue.reclaim_stale(stale_after_s)
        if not process_one(queue, deps, worker_id):
            time.sleep(poll_interval_s)


def _main() -> None:
    import os
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from .config import ContourConfig
    from .corpus import CorpusStore
    from .db import apply_migrations, connect_sqlite
    from .providers import build_registry
    from .queue import PostgresJobQueue, SqliteJobQueue

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    cfg = ContourConfig.from_env()
    if cfg.pg_dsn:
        queue: "SqliteJobQueue | PostgresJobQueue" = PostgresJobQueue(cfg.pg_dsn)
        conn = queue.conn
    else:
        conn = connect_sqlite(cfg.db_path)
        queue = SqliteJobQueue(conn)
    apply_migrations(conn)
    deps = LoopDeps(providers=build_registry(cfg.provider_backend),
                    corpus=CorpusStore(conn), config=cfg)
    run_forever(queue, deps)


if __name__ == "__main__":
    _main()
