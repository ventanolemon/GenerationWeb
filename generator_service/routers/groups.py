"""
Группы и назначение преподавателей.

Admin-управление (создание группы, состав, назначение преподавателей):
  GET    /admin/groups
  POST   /admin/groups                       {name}
  POST   /admin/groups/{gid}/members         {login}
  DELETE /admin/groups/{gid}/members/{login}
  POST   /admin/groups/{gid}/teachers        {login}
  DELETE /admin/groups/{gid}/teachers/{login}

Teacher read-view своих групп (payoff назначения):
  GET    /groups/mine

Логика — core/groups_api.py (headless). Идентичность обязательна (401 без
X-User-Id, как /analytics и /admin); admin-эндпоинты требуют роль admin
(403 иначе); доменные ошибки (GroupActionError) → 400.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import groups_api

router = APIRouter(tags=["groups"])


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)


def _identity(x_user_id: Optional[str], x_user_role: Optional[str]):
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    return uid, (x_user_role or "").strip().lower()


def _require_admin(x_user_id: Optional[str], x_user_role: Optional[str]) -> str:
    uid, role = _identity(x_user_id, x_user_role)
    if role != "admin":
        raise HTTPException(status_code=403,
                            detail="Доступно только администратору.")
    return uid


def _guard(fn):
    try:
        return fn()
    except groups_api.GroupActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Admin: управление группами ----------

@router.get("/admin/groups")
def get_groups(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return {"groups": groups_api.list_groups(request.app.state.repo)}


@router.post("/admin/groups")
def create_group(
    body: CreateGroupRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    actor = _require_admin(x_user_id, x_user_role)
    return _guard(lambda: groups_api.create_group(
        request.app.state.repo, name=body.name, actor_login=actor))


@router.post("/admin/groups/{group_id}/members")
def add_member(
    group_id: int,
    body: LoginRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return _guard(lambda: groups_api.add_member(
        request.app.state.repo, group_id=group_id, login=body.login))


@router.delete("/admin/groups/{group_id}/members/{login}")
def remove_member(
    group_id: int,
    login: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return _guard(lambda: groups_api.remove_member(
        request.app.state.repo, group_id=group_id, login=login))


@router.post("/admin/groups/{group_id}/teachers")
def assign_teacher(
    group_id: int,
    body: LoginRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return _guard(lambda: groups_api.assign_teacher(
        request.app.state.repo, group_id=group_id, login=body.login))


@router.delete("/admin/groups/{group_id}/teachers/{login}")
def unassign_teacher(
    group_id: int,
    login: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return _guard(lambda: groups_api.unassign_teacher(
        request.app.state.repo, group_id=group_id, login=login))


# ---------- Teacher: свои группы ----------

@router.get("/groups/mine")
def my_groups(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    uid, _role = _identity(x_user_id, x_user_role)
    return {"groups": groups_api.teacher_groups(
        request.app.state.repo, teacher_login=uid)}
