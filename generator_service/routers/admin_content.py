"""
Хранилища контента: обзор и перенос предметов между личным и общим.

  GET  /admin/content                          что где лежит (admin)
  POST /admin/content/{subject_id}/publish     личное → общее (admin)
  POST /admin/content/{subject_id}/assign      общее → личное (admin)
  GET  /admin/content/{subject_id}/public       кому доступен наружу (admin)
  GET  /subjects/mine                          своё личное хранилище (teacher)

Переносит только админ. Преподаватель кладёт в СВОЁ личное хранилище сам —
создавая предмет на десктопе и отправляя его синком (`/sync/push` назначает
владельцем автора запроса), — но решение «это годится всем» продуктовое, и
принимает его администратор.

Логика — core/content_api.py (headless), роутер адаптирует HTTP.
"""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import content_api

from ..identity import AdminUser, CurrentUser, SuperUser

router = APIRouter(tags=["content"])


class AssignRequest(BaseModel):
    login: str = Field(..., min_length=1,
                       description="Кому в личное хранилище")


def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except content_api.ContentActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/content")
def get_overview(
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Обзор сужен до своей организации; администратор развёртывания видит
    всё. Раньше ручка смешивала личное и общее по всему развёртыванию —
    после §8 это означало бы показывать чужие организации."""
    return content_api.overview(
        request.app.state.repo,
        organization_id=None if who.is_superuser else who.organization_id)


@router.post("/admin/content/{subject_id}/publish")
def post_publish(
    subject_id: int,
    request: Request,
    who: SuperUser,
) -> dict[str, Any]:
    """Личное → общее: предмет становится ВСТРОЕННЫМ — видимым всем
    организациям сразу. По §8.1 это единственное, что пересекает границу
    контейнера, поэтому решение принадлежит развёртыванию, а не
    организации: иначе любой админ кафедры раздавал бы контент всему вузу."""
    return _run(content_api.publish, request.app.state.repo,
                subject_id=subject_id, actor_login=who.login)


@router.post("/admin/content/{subject_id}/assign")
def post_assign(
    subject_id: int,
    body: AssignRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Общее → личное указанного преподавателя (или передача между личными).
    Публичный доступ к предмету при этом снимается — см. content_api."""
    return _run(content_api.assign_to, request.app.state.repo,
                subject_id=subject_id, login=body.login, actor_login=who.login)


@router.get("/admin/content/{subject_id}/public")
def get_public_visibility(
    subject_id: int,
    request: Request,
    who: SuperUser,
) -> dict[str, Any]:
    """Кому предмет виден наружу. Следует за решением по API-клиентам: они
    остаются на уровне развёртывания, значит и диагностика — тоже."""
    return content_api.public_visibility(request.app.state.repo, subject_id)


@router.get("/subjects/mine")
def get_mine(
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    """Своё личное хранилище. Доступно любой опознанной роли: у студента оно
    просто пустое, и отдельный запрет тут ничего не защищает."""
    return content_api.list_mine(request.app.state.repo, actor_login=who.login)
