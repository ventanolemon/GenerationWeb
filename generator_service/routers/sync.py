"""
Offline-sync десктопа: push → pull (offline_sync_protocol.md §4).

  POST /sync/push  {device_id, attempts[], word_stats_deltas[], changed_entities[]}
                   → {attempts_received, attempts_new, accepted[], conflicts[]}
  POST /sync/pull  {device_id, cursors{subjects, partitions}, limit?}
                   → {subjects[], partitions[], deleted[], new_cursors, has_more,
                      resources{catalog_version}}

Логика — в core/sync_api.py (headless, как graph_api): роутер только
адаптирует HTTP. Развилка «где живёт sync» решена в пользу generator_service:
у него прямой Repository и все детерминированные операции над данными уже
здесь (partitions.py — та же конвенция); web_layer добавит JWT-проверку и
тонкий прокси (паттерн GeneratorClient.cs), когда auth-фаза дойдёт.

Identity — заголовки X-User-Id / X-User-Role (как contour_service): без них
область видимости — dev-заглушка «видно всё» (core.sync_api.visible_scope),
с ними — Repository.visible_subject_ids (RBAC Фаза 1).

Порядок на клиенте: сначала push, потом pull — иначе pull затрёт
base_version живых правок (§4).
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from core import sync_api

router = APIRouter(prefix="/sync", tags=["sync"])


class PushRequest(BaseModel):
    device_id: str = Field(..., min_length=1)
    attempts: list[dict] = Field(default_factory=list)
    word_stats_deltas: list[dict] = Field(default_factory=list)
    changed_entities: list[dict] = Field(default_factory=list)
    # Ключ WordStats (login/guest-uuid) — легаси-таблица строковая;
    # по умолчанию X-User-Id либо device_id.
    user_key: Optional[str] = None


class PullRequest(BaseModel):
    device_id: str = Field(..., min_length=1)
    cursors: dict = Field(default_factory=dict)  # {"subjects": 42, "partitions": 107}
    limit: int = Field(default=sync_api.DEFAULT_PAGE_LIMIT, ge=1,
                       le=sync_api.MAX_PAGE_LIMIT)


def _identity(x_user_id: Optional[str], x_user_role: Optional[str]):
    try:
        uid = int(x_user_id) if x_user_id else None
    except ValueError:
        uid = None
    role = (x_user_role or "teacher").strip().lower()
    return uid, role


@router.post("/push")
def sync_push(
    body: PushRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Принять офлайн-изменения устройства. Идемпотентно: повторная отправка
    того же пакета после обрыва безвредна (attempts — по client_uuid,
    version-check сущностей — по base_version)."""
    uid, role = _identity(x_user_id, x_user_role)
    result = sync_api.push(
        request.app.state.repo,
        device_id=body.device_id,
        user_id=uid,
        role=role,
        attempts=body.attempts,
        word_stats_deltas=body.word_stats_deltas,
        changed_entities=body.changed_entities,
        user_key=body.user_key,
    )
    # Правки сущностей могли поменять партиции — реестр генераторов
    # пересобирается, как после обычного upsert (см. partitions.py).
    if body.changed_entities:
        from .partitions import _rebuild
        _rebuild(request)
    return result


@router.post("/pull")
def sync_pull(
    body: PullRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Отдать диф по курсорам (включая tombstones) страницами."""
    uid, role = _identity(x_user_id, x_user_role)
    return sync_api.pull(
        request.app.state.repo,
        device_id=body.device_id,
        user_id=uid,
        role=role,
        cursors=body.cursors,
        limit=body.limit,
    )
