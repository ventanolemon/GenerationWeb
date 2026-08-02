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
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import content_api

router = APIRouter(tags=["content"])


class AssignRequest(BaseModel):
    login: str = Field(..., min_length=1,
                       description="Кому в личное хранилище")


def _identity(x_user_id: Optional[str], x_user_role: Optional[str]):
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    return uid, (x_user_role or "student").strip().lower()


def _require_admin(x_user_id: Optional[str], x_user_role: Optional[str]) -> str:
    uid, role = _identity(x_user_id, x_user_role)
    if role != "admin":
        raise HTTPException(status_code=403,
                            detail="Переносить контент может только админ.")
    return uid


def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except content_api.ContentActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/content")
def get_overview(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return content_api.overview(request.app.state.repo)


@router.post("/admin/content/{subject_id}/publish")
def post_publish(
    subject_id: int,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Личное → общее: предмет становится доступен всем и переходит под
    администрирование продукта."""
    actor = _require_admin(x_user_id, x_user_role)
    return _run(content_api.publish, request.app.state.repo,
                subject_id=subject_id, actor_login=actor)


@router.post("/admin/content/{subject_id}/assign")
def post_assign(
    subject_id: int,
    body: AssignRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Общее → личное указанного преподавателя (или передача между личными).
    Публичный доступ к предмету при этом снимается — см. content_api."""
    actor = _require_admin(x_user_id, x_user_role)
    return _run(content_api.assign_to, request.app.state.repo,
                subject_id=subject_id, login=body.login, actor_login=actor)


@router.get("/admin/content/{subject_id}/public")
def get_public_visibility(
    subject_id: int,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return content_api.public_visibility(request.app.state.repo, subject_id)


@router.get("/subjects/mine")
def get_mine(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Своё личное хранилище. Доступно любой опознанной роли: у студента оно
    просто пустое, и отдельный запрет тут ничего не защищает."""
    uid, _ = _identity(x_user_id, x_user_role)
    return content_api.list_mine(request.app.state.repo, actor_login=uid)
