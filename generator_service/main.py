"""
Точка входа FastAPI-микросервиса.

Запуск из корня монорепо (важно — из корня, чтобы импорты `bootstrap`
и `const` нашлись):

    uvicorn generator_service.main:app --host 127.0.0.1 --port 8000

Swagger UI: http://127.0.0.1:8000/docs

Lifespan:
  - при старте  : sync_database + build_registry (это код десктоп-репо,
                  без правок)
  - при остановке: ничего особенного

CORS: включается переменной окружения GENERATOR_CORS_ORIGINS (через запятую).
В production обычно не нужен — браузер ходит только в ASP.NET, а тот
гоняет приватные запросы к FastAPI без браузера. Включаем для разработки,
чтобы можно было дёргать FastAPI напрямую из Vite-dev-сервера или Postman.

Пример:
    export GENERATOR_CORS_ORIGINS="http://localhost:5173,http://localhost:5000"
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bootstrap import build_registry, sync_database
from const import DB_PATH, WORDS_DIR
from core import Repository

from .routers import auth as auth_router
from .routers import export as export_router
from .routers import generate as generate_router
from .routers import interactive as interactive_router
from .routers import meta as meta_router
from .routers import partitions as partitions_router
from .routers import subjects as subjects_router
from .session_store import SessionStore


logger = logging.getLogger("generator_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Готовим Repository и Registry при старте — один раз на жизнь процесса."""
    logger.info("Initializing generator service…")
    repo = Repository(DB_PATH)
    sync_database(repo, WORDS_DIR)
    registry = build_registry(repo, WORDS_DIR)

    app.state.repo = repo
    app.state.registry = registry
    app.state.sessions = SessionStore()
    logger.info(
        "Generator service ready. Registered generators: %d",
        len(registry.all_ids()),
    )
    yield
    logger.info("Generator service shutting down.")


app = FastAPI(
    title="Generator Microservice",
    description=(
        "Внутренний микросервис над ядром генератора учебных заданий. "
        "Не предназначен для прямого обращения из браузера — это API "
        "для ASP.NET Core Web Layer."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------- CORS (опционально, для разработки) ----------

cors_origins_env = os.environ.get("GENERATOR_CORS_ORIGINS", "").strip()
if cors_origins_env:
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS enabled for: %s", origins)


# ---------- Роутеры ----------

app.include_router(auth_router.router)
app.include_router(subjects_router.router)
app.include_router(generate_router.router)
app.include_router(interactive_router.router)
app.include_router(export_router.router)
app.include_router(partitions_router.router)
app.include_router(meta_router.router)
