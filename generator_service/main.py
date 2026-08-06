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
from core import (InteractiveTask, Repository, WordStatsStore,
                  session_from_task)

from . import errors
from .context import current_user_id as current_user_id_var
from .routers import admin as admin_router
from .routers import admin_clients as admin_clients_router
from .routers import admin_content as admin_content_router
from .routers import assignments as assignments_router
from .routers import analytics as analytics_router
from .routers import answers as answers_router
from .routers import auth as auth_router
from .routers import groups as groups_router
from .routers import export as export_router
from .routers import generate as generate_router
from .routers import grants as grants_router
from .routers import graph as graph_router
from .routers import interactive as interactive_router
from .routers import meta as meta_router
from .routers import packages as packages_router
from .routers import partitions as partitions_router
from .routers import public_v1 as public_v1_router
from .routers import stats as stats_router
from .routers import subjects as subjects_router
from .routers import sync as sync_router
from .routers import updates as updates_router
from .session_store import SessionStore


logger = logging.getLogger("generator_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Готовим Repository и Registry при старте — один раз на жизнь процесса."""
    logger.info("Initializing generator service…")
    repo = Repository(DB_PATH)
    sync_database(repo, WORDS_DIR)
    stats_store = WordStatsStore(repo)
    registry = build_registry(
        repo, WORDS_DIR,
        stats_store=stats_store,
        user_id_provider=lambda: current_user_id_var.get(),
    )

    def revive_interactive_task(partition_id: int, user_id):
        """
        Пересобрать интерактивное задание для сессии, поднятой из БД.

        Читает `app.state.registry`, а не замкнутый `registry`: реестр
        пересобирается при каждой правке разделов (`partitions._rebuild`), и
        замыкание на стартовый экземпляр отдавало бы устаревшие генераторы.

        user_id кладётся в тот же ContextVar, что и обычная генерация:
        тренажёр слов берёт из него межсессионную статистику, и без этого
        воскрешённая сессия писала бы прогресс в чужой (гостевой) бакет.
        """
        current_user_id_var.set(user_id)
        current_registry = app.state.registry
        if not current_registry.has(partition_id):
            return None
        partition = repo.get_partition(partition_id)
        task = current_registry.get(
            partition_id, partition.generation_params if partition else {}
        ).generate()
        if isinstance(task, InteractiveTask):
            return task
        # Статическое задание со спецификацией ответа: сессию над ним ведёт
        # общая машинка. Пересборка даёт ДРУГОЕ случайное задание — это
        # нормально, потому что restore() тут же заместит его вопросы теми,
        # что лежат в снимке. Оболочка нужна только чтобы было куда их
        # положить.
        return session_from_task(task)

    app.state.repo = repo
    app.state.registry = registry
    app.state.sessions = SessionStore(
        repo=repo, task_factory=revive_interactive_task)
    app.state.stats_store = stats_store
    logger.info(
        "Generator service ready. Registered generators: %d",
        len(registry.all_ids()),
    )
    yield
    # Рабочий процесс исполнения графов переживёт родителя, если его не
    # снять: он ждёт на stdin, который никто больше не закроет.
    try:
        from core.graph.isolation import shutdown_shared
        shutdown_shared()
    except Exception:                              # noqa: BLE001
        logger.exception("не удалось снять рабочий процесс графов")
    logger.info("Generator service shutting down.")


app = FastAPI(
    title="Generator Microservice",
    description=(
        "Внутренний микросервис над ядром генератора учебных заданий. "
        "Не предназначен для прямого обращения из браузера — это API "
        "для ASP.NET Core Web Layer.\n\n"
        "**Ошибки** отдаются единым конвертом "
        "`{error: {code, message, request_id}}` "
        "(см. `generator_service/errors.py`). Поле `detail` дублирует "
        "`error.message` и оставлено для совместимости с десктопными "
        "клиентами — новым читателям следует опираться на `error`.\n\n"
        "Заголовок `X-Request-Id` пробрасывается насквозь: пришедший "
        "снаружи возвращается как есть, иначе генерируется — по нему "
        "ответ соотносится с логом."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "auth", "description": "Вход, регистрация, профиль."},
        {"name": "subjects", "description": "Справочник предметов и разделов."},
        {"name": "generate", "description": "Генерация задания по разделу."},
        {"name": "interactive",
         "description": "Ходы интерактивной сессии (тренажёр)."},
        {"name": "answers",
         "description": "Предпросмотр «что примут» для преподавателя."},
        {"name": "partitions", "description": "CRUD разделов."},
        {"name": "graph", "description": "Каталог узлов, валидация, превью."},
        {"name": "sync", "description": "Offline-синхронизация десктопа."},
        {"name": "grants", "description": "Выдача предметов преподавателям."},
        {"name": "content",
         "description": "Хранилища контента: личное преподавателя и общее, "
                        "перенос между ними."},
        {"name": "admin", "description": "Пользователи, роли, группы."},
        {"name": "assignments", "description": "Домашние задания группам."},
        {"name": "analytics", "description": "Сводки успеваемости."},
        {"name": "stats", "description": "Статистика по словам."},
        {"name": "export", "description": "Экспорт вариантов."},
        {"name": "packages",
         "description": "Пакеты узлов графа: односторонняя докачка "
                        "с сервера, подпись общая с релизами."},
        {"name": "updates",
         "description": "Обновление десктопа: подписанные релизы. "
                        "Сервер раздаёт, но не подписывает."},
        {"name": "meta", "description": "Служебное: health, версия."},
        {"name": "public-v1",
         "description": "Публичный API для сторонних приложений. Субъект — "
                        "ключ приложения (Authorization: Bearer), а не "
                        "пользователь; идентификаторы публичные и стабильные. "
                        "Единственная поверхность с обещанием совместимости."},
    ],
    lifespan=lifespan,
)

# Единый конверт ошибки — до роутеров, чтобы накрыть их все разом.
errors.install(app)


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
# Выше subjects_router: /subjects/grants/mine — литеральный маршрут, и пусть
# он объявляется раньше параметрических соседей по префиксу /subjects.
app.include_router(grants_router.router)
# Выше subjects_router по той же причине: /subjects/mine — литерал.
app.include_router(admin_content_router.router)
app.include_router(subjects_router.router)
app.include_router(generate_router.router)
app.include_router(interactive_router.router)
app.include_router(answers_router.router)
app.include_router(export_router.router)
app.include_router(partitions_router.router)
app.include_router(stats_router.router)
app.include_router(meta_router.router)
app.include_router(graph_router.router)
app.include_router(sync_router.router)
app.include_router(updates_router.router)
app.include_router(packages_router.router)
app.include_router(analytics_router.router)
app.include_router(admin_router.router)
app.include_router(groups_router.router)
app.include_router(admin_clients_router.router)
# Публичная поверхность: единственная с обещанием совместимости.
app.include_router(public_v1_router.router)
app.include_router(assignments_router.router)
