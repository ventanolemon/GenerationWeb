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

Логика — core/groups_api.py (headless). Личность и роль приходят из
generator_service/identity.py — одного резолвера на весь сервис; доменные
ошибки (GroupActionError) → 400.
"""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import groups_api

from ..identity import AdminUser, CurrentUser

router = APIRouter(tags=["groups"])


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)


def _guard(fn):
    try:
        return fn()
    except groups_api.GroupActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Admin: управление группами ----------

@router.get("/admin/groups")
def get_groups(
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return {"groups": groups_api.list_groups(request.app.state.repo)}


@router.post("/admin/groups")
def create_group(
    body: CreateGroupRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _guard(lambda: groups_api.create_group(
        request.app.state.repo, name=body.name, actor_login=who.login))


@router.post("/admin/groups/{group_id}/members")
def add_member(
    group_id: int,
    body: LoginRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _guard(lambda: groups_api.add_member(
        request.app.state.repo, group_id=group_id, login=body.login))


@router.delete("/admin/groups/{group_id}/members/{login}")
def remove_member(
    group_id: int,
    login: str,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _guard(lambda: groups_api.remove_member(
        request.app.state.repo, group_id=group_id, login=login))


@router.post("/admin/groups/{group_id}/teachers")
def assign_teacher(
    group_id: int,
    body: LoginRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _guard(lambda: groups_api.assign_teacher(
        request.app.state.repo, group_id=group_id, login=body.login))


@router.delete("/admin/groups/{group_id}/teachers/{login}")
def unassign_teacher(
    group_id: int,
    login: str,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _guard(lambda: groups_api.unassign_teacher(
        request.app.state.repo, group_id=group_id, login=login))


# ---------- Teacher: свои группы ----------

@router.get("/groups/mine")
def my_groups(
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    return {"groups": groups_api.teacher_groups(
        request.app.state.repo, teacher_login=who.login)}
