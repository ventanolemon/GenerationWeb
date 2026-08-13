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

from core import grants_api, organizations_api

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
    return grants_api.admin_matrix(
        request.app.state.repo,
        organization_id=None if who.is_superuser else who.organization_id)


@router.put("/admin/subject-grants/default-access")
def put_default_access(
    body: DefaultAccessRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Умолчание видимости — настройка ОРГАНИЗАЦИИ (§8.1): выдачи работают
    внутри неё, значит и умолчание для них живёт там же. Раньше это была
    одна строка app_settings на всё развёртывание."""
    repo = request.app.state.repo
    if who.organization_id is None:
        raise HTTPException(
            status_code=400,
            detail="Вы не состоите в организации — настраивать нечего.")
    try:
        out = organizations_api.set_default_access(
            repo, org_id=who.organization_id, value=body.default_access)
    except organizations_api.OrganizationActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Форма ответа прежняя: её читают фронт и десктоп, и менять её заодно с
    # переездом настройки в организацию значило бы сломать их без нужды.
    return {"ok": True, "default_access": out["default_subject_access"],
            "organization_id": out["organization_id"]}


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
