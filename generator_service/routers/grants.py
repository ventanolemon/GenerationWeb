"""
Выдача предметов преподавателям (docs/subject_grants.md в репозитории
Generator) — серверная половина, зеркало core/grants/client.py десктопа.

  GET /subjects/grants/mine                — свои выдачи (любая роль)
  GET /admin/subject-grants                — данные матрицы (admin)
  PUT /admin/subject-grants/default-access — режим умолчания (admin)
  PUT /admin/subject-grants/{login}        — выдачи преподавателя целиком (admin)

Логика — core/grants_api.py (headless), роутер адаптирует HTTP и проверяет
identity вызывающего: заголовки X-User-Id / X-User-Role, как у sync, admin,
groups и контура. Права server-authoritative — клиентский `can_manage()`
гейтит вкладку в UI, но не заменяет проверку здесь.

Порядок объявления админских маршрутов значим: `default-access` — литерал, и
объявлен он ВЫШЕ `{login}`, иначе параметрический маршрут перехватил бы его и
режим умолчания стал бы выдачей преподавателю с логином «default-access».
"""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import grants_api

from ..identity import AdminUser, CurrentUser

router = APIRouter(tags=["grants"])


class SetGrantsRequest(BaseModel):
    # Полный набор, не дельта: матрица правится строкой, идемпотентность
    # важнее экономии — повторное применение того же набора ничего не меняет,
    # а отзыв не требует отдельной операции.
    subject_ids: list[int] = Field(default_factory=list)


class DefaultAccessRequest(BaseModel):
    default_access: str = Field(..., min_length=1)


@router.get("/subjects/grants/mine")
def get_my_grants(
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    """Свои выдачи. Десктоп зовёт при логине и при каждом sync."""
    return grants_api.my_grants(request.app.state.repo,
                                actor_login=who.login, role=who.role)


@router.get("/admin/subject-grants")
def get_matrix(
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return grants_api.admin_matrix(request.app.state.repo)


@router.put("/admin/subject-grants/default-access")
def put_default_access(
    body: DefaultAccessRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    try:
        return grants_api.set_default_access(
            request.app.state.repo, default_access=body.default_access)
    except grants_api.GrantActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/subject-grants/{login}")
def put_teacher_grants(
    login: str,
    body: SetGrantsRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    try:
        return grants_api.set_teacher_grants(
            request.app.state.repo, actor_login=who.login,
            target_login=login, subject_ids=body.subject_ids,
        )
    except grants_api.GrantActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
