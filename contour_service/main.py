"""
Точка входа FastAPI-сервиса контура. Запуск из корня монорепо (важно —
импорты `const`/`core` находятся от корня):

    uvicorn contour_service.main:app --host 127.0.0.1 --port 8001

Swagger UI: http://127.0.0.1:8001/docs

Lifespan:
  - при старте: соединение с БД (SQLite-файл монорепо или Postgres по
    CONTOUR_PG_DSN), идемпотентные миграции contour-таблиц, реестр
    провайдеров (CONTOUR_PROVIDER=mock|anthropic), Repository для записи
    партиций из approve, фоновая asyncio-задача воркера;
  - CONTOUR_WORKER_DISABLED=1 отключает встроенный воркер (когда воркеры
    подняты отдельными процессами `python -m contour_service.worker`
    или в тестах, где петлю дёргают синхронно).

Сервис — приватная сеть: личность приходит заголовками X-User-Id /
X-User-Role только от web_layer (system_topology.md §6).
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Корень монорепо — для импортов const/core при запуске из любого cwd.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI

from const import DB_PATH
from core import Repository

from .config import ContourConfig
from .corpus import CorpusStore
from .db import apply_migrations, connect_sqlite
from .loop import LoopDeps
from .providers import build_registry
from .queue import PostgresJobQueue, SqliteJobQueue
from .routers import corpus as corpus_router
from .routers import jobs as jobs_router
from .worker import process_one

logger = logging.getLogger("contour_service")


async def _worker_loop(app: FastAPI, poll_interval_s: float = 2.0) -> None:
    """Фоновый воркер: очередь опрашивается в thread-pool'е (петля — sync)."""
    deps: LoopDeps = app.state.contour_deps
    queue = app.state.contour_queue
    while True:
        try:
            queue.reclaim_stale(30 * 60.0)
            busy = await asyncio.to_thread(process_one, queue, deps)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("worker loop error: %s", e)
            busy = False
        if not busy:
            await asyncio.sleep(poll_interval_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing contour service…")
    cfg = ContourConfig.from_env()

    if cfg.pg_dsn:
        queue: "SqliteJobQueue | PostgresJobQueue" = PostgresJobQueue(cfg.pg_dsn)
        conn = queue.conn
    else:
        conn = connect_sqlite(cfg.db_path or DB_PATH)
        queue = SqliteJobQueue(conn)
    apply_migrations(conn)

    providers = build_registry(cfg.provider_backend)
    corpus = CorpusStore(conn)

    app.state.contour_config = cfg
    app.state.contour_queue = queue
    app.state.contour_corpus = corpus
    app.state.contour_providers = providers
    app.state.contour_deps = LoopDeps(
        providers=providers, corpus=corpus, config=cfg)
    # Партиции approve пишет через существующий Repository (та же БД/формат).
    app.state.repo = Repository(cfg.db_path or DB_PATH)

    worker_task = None
    if os.environ.get("CONTOUR_WORKER_DISABLED", "").strip() not in ("1", "true"):
        worker_task = asyncio.create_task(_worker_loop(app))
    logger.info("Contour service ready (provider backend: %s).",
                cfg.provider_backend)
    yield
    if worker_task is not None:
        worker_task.cancel()
    logger.info("Contour service shutting down.")


app = FastAPI(
    title="Contour Microservice",
    description=(
        "Сервис LLM-петли S0–S6: job-очередь, реестр нейропровайдеров, "
        "оркестратор closed_loop_contract.md. Не предназначен для прямого "
        "обращения из браузера — это API для ASP.NET Core Web Layer."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs_router.router)
app.include_router(corpus_router.router)
