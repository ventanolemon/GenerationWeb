"""
Публичный API v1 — поверхность для сторонних приложений.

  GET  /v1/me                      кто я, сколько квоты осталось
  GET  /v1/catalog                 что доступно этому ключу
  POST /v1/tasks                   сгенерировать задание   ← основная
  POST /v1/tasks/{session}/answer  ход интерактивной сессии

Отличается от внутреннего `/api/*` тремя вещами, и все три — намеренно:

1. **Субъект — приложение**, а не человек: `Authorization: Bearer <ключ>`
   вместо `X-User-Id`. Роли здесь нет; есть скоуп ключа и его квота.
2. **Идентификаторы публичные** (`topic_id` — uuid, не `partition_id`), тип
   темы — словарное слово, не число `constracted`. Внутренняя схема наружу
   не протекает: см. `core/public_api.py`.
3. **Обещание совместимости.** `/v1` не ломается; всё, что меняется без
   предупреждения, живёт во внутреннем `/api/*`.

Где это стоит в сети: `generator_service` остаётся внутренним, наружу его
не публикуют (`system_topology.md` §6.2). Публичный вход — `web_layer`,
который релеит `/api/v1/*` сюда, добавляя TLS, CORS и лимиты соединений.
Ключи проверяются здесь, а не в релее, потому что проверка неотделима от
скоупа контента: и то и другое читается из одной БД одним запросом.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import InteractiveTask, StaticTask, api_clients, public_api
from ..context import current_user_id as current_user_id_var

router = APIRouter(prefix="/v1", tags=["public-v1"])


class CreateTaskRequest(BaseModel):
    topic_id: str = Field(..., min_length=1,
                          description="Публичный id темы из /v1/catalog")
    # Ключ конечного пользователя на стороне интегратора: по нему считается
    # межсессионная статистика тренажёра. Свободная строка — мы про
    # пользователей интегратора ничего не знаем и знать не должны.
    end_user: Optional[str] = Field(
        None, max_length=200,
        description="Необязательный идентификатор конечного пользователя")


class AnswerRequest(BaseModel):
    answer: str = Field(..., description="Ответ пользователя")
    tolerant: bool = Field(False, description="Принимать мелкие опечатки")


def _client(request: Request, authorization: Optional[str],
            origin: Optional[str]) -> dict:
    """Проверить Bearer-ключ. Ошибки едут стандартным конвертом сервиса."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        return api_clients.authenticate(request.app.state.repo, token, origin)
    except api_clients.ApiAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _count(request: Request, client: dict) -> None:
    try:
        api_clients.check_and_count(request.app.state.repo, client)
    except api_clients.ApiAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/me")
def get_me(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    origin: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    repo = request.app.state.repo
    client = _client(request, authorization, origin)
    return public_api.me_payload(
        client, api_clients.usage_snapshot(repo, client),
        subject_count=len(api_clients.client_subject_ids(
            repo, client["client_id"])),
    )


@router.get("/catalog")
def get_catalog(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    origin: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Каталог квоту не тратит: аккуратная интеграция сверяется с ним перед
    каждым запросом, и брать за это плату значило бы поощрять обратное."""
    client = _client(request, authorization, origin)
    return public_api.catalog(
        request.app.state.repo, client["client_id"],
        registry=getattr(request.app.state, "registry", None),
    )


@router.post("/tasks")
def create_task(
    body: CreateTaskRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    origin: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    repo = request.app.state.repo
    registry = request.app.state.registry
    sessions = request.app.state.sessions
    client = _client(request, authorization, origin)

    try:
        partition_id = public_api.resolve_topic(
            repo, client["client_id"], body.topic_id)
    except public_api.PublicApiError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _count(request, client)

    # Статистика конечного пользователя интегратора живёт в своём
    # пространстве имён: без префикса чужой «ivanov» слился бы с нашим.
    user_key = (f"api:{client['client_id']}:{body.end_user}"
                if body.end_user else None)
    current_user_id_var.set(user_key)

    if not registry.has(partition_id):
        raise HTTPException(status_code=404,
                            detail=f"Тема {body.topic_id!r} не найдена.")
    partition = repo.get_partition(partition_id)
    try:
        generator = registry.get(
            partition_id, partition.generation_params if partition else {})
        task = generator.generate()
    except HTTPException:
        raise
    except Exception as exc:
        # Наружу — без внутренностей генератора: имя класса и текст
        # исключения интегратору ничего не дают, а нам это утечка.
        raise HTTPException(
            status_code=500,
            detail="Не удалось сгенерировать задание.") from exc

    if isinstance(task, StaticTask):
        return public_api.task_payload(repo, partition_id, task.to_dict())
    if isinstance(task, InteractiveTask):
        session_id = sessions.create(task, partition_id, user_key)
        return public_api.interactive_payload(
            repo, partition_id, session_id,
            [b.to_dict() for b in task.initial_prompt()],
            supports_tolerant=hasattr(task, "tolerant"),
        )
    raise HTTPException(status_code=500,
                        detail="Не удалось сгенерировать задание.")


@router.post("/tasks/{session_id}/answer")
def answer_task(
    session_id: str,
    body: AnswerRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    origin: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """
    Ход интерактивной сессии. Квоту не тратит: тарифицируется выданное
    задание, а не разговор по нему — иначе длинный тренажёр стоил бы
    интегратору дороже короткого при одинаковой пользе.
    """
    sessions = request.app.state.sessions
    _client(request, authorization, origin)

    task = sessions.get(session_id)
    if task is None:
        raise HTTPException(status_code=404,
                            detail="Сессия не найдена или истекла.")
    if hasattr(task, "tolerant"):
        task.tolerant = body.tolerant
    try:
        result = task.submit(body.answer).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail="Не удалось обработать ответ.") from exc

    if result.get("next_prompt") is None:
        sessions.remove(session_id)
    else:
        sessions.save(session_id)
    return public_api.turn_payload(result, session_id)
