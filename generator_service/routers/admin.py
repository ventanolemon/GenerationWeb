"""
GET  /admin/users              — список пользователей (admin-only)
POST /admin/users/{login}/role — сменить роль (admin-only; без self-elevation,
                                  без понижения последнего администратора)
GET  /admin/deployment         — состояние развёртывания (только суперадмин)

Логика — core/admin_api.py (headless), роутер адаптирует HTTP. Личность и
роль приходят из generator_service/identity.py — одного резолвера на весь
сервис; своей копии гейта здесь больше нет.
"""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import admin_api

from ..identity import AdminUser, SuperUser

router = APIRouter(prefix="/admin", tags=["admin"])


class ChangeRoleRequest(BaseModel):
    role: str = Field(..., min_length=1)


@router.get("/users")
def get_users(request: Request, who: AdminUser) -> dict[str, Any]:
    return {"users": admin_api.list_users(
        request.app.state.repo,
        organization_id=None if who.is_superuser else who.organization_id)}


@router.post("/users/{login}/role")
def post_change_role(
    login: str,
    body: ChangeRoleRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    try:
        return admin_api.change_role(
            request.app.state.repo, actor_login=who.login,
            target_login=login, new_role=body.role,
            actor_organization_id=(None if who.is_superuser
                                   else who.organization_id),
        )
    except admin_api.AdminActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/deployment")
def get_deployment(request: Request, who: SuperUser) -> dict[str, Any]:
    """
    Состояние развёртывания: то, что задано окружением, а не данными.

    Пока здесь одна запись, и она же — причина ручку завести. Флаг
    `GEN_TRUST_IDENTITY_HEADERS` выключен по умолчанию, но развёртыванию с
    необновлёнными десктопами его можно включить «ненадолго». Единственным
    следом этого была строка в логе сервера — а лог никто не перечитывает,
    и «ненадолго» становится навсегда. Теперь режим видно оттуда, откуда
    им управляют.

    Только суперадминистратор: это свойство развёртывания, а не
    организации, и администратору кафедры оно не адресовано.
    """
    from core.auth_sessions import trust_headers

    return {"trust_identity_headers": trust_headers()}
