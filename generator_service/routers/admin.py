"""
GET  /admin/users              — список пользователей (admin-only)
POST /admin/users/{login}/role — сменить роль (admin-only; без self-elevation,
                                  без понижения последнего администратора)

Логика — core/admin_api.py (headless), роутер адаптирует HTTP и проверяет
identity вызывающего: идентичность обязательна (как /analytics — без
sync-style dev-заглушки «видно всё»), роль обязана быть admin (403 иначе).
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import admin_api

router = APIRouter(prefix="/admin", tags=["admin"])


class ChangeRoleRequest(BaseModel):
    role: str = Field(..., min_length=1)


def _require_admin(x_user_id: Optional[str], x_user_role: Optional[str]) -> str:
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    role = (x_user_role or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403,
                            detail="Доступно только администратору.")
    return uid


@router.get("/users")
def get_users(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return {"users": admin_api.list_users(request.app.state.repo)}


@router.post("/users/{login}/role")
def post_change_role(
    login: str,
    body: ChangeRoleRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    actor = _require_admin(x_user_id, x_user_role)
    try:
        return admin_api.change_role(
            request.app.state.repo, actor_login=actor,
            target_login=login, new_role=body.role,
        )
    except admin_api.AdminActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
