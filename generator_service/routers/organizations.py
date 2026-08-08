"""
Организации (§8 плана).

GET    /admin/organizations                  — список (администратор развёртывания)
POST   /admin/organizations                  — завести
GET    /admin/organizations/{id}             — одна, с составом
PATCH  /admin/organizations/{id}             — переименовать
POST   /admin/organizations/{id}/owner       — передать владение
POST   /admin/organizations/{id}/members     — принять пользователя
DELETE /admin/organizations/{id}/members/{login} — исключить
GET    /organizations/mine                   — своя организация (любая роль)
POST   /admin/superusers/{login}             — выдать/снять админа развёртывания

Кто что может:

* заводить, переименовывать организации и раздавать флаг администратора
  развёртывания — только администратор РАЗВЁРТЫВАНИЯ (`is_superuser`);
* принимать и исключать людей — админ своей организации;
* передавать владение — владелец организации, а также администратор
  развёртывания (§8.2: единственный запасной путь для организации,
  оставшейся без доступного владельца, — без него «владельца нельзя
  понизить» превращается в ловушку).

Логика — core/organizations_api.py (headless).
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import organizations_api

from ..identity import AdminUser, CurrentUser, SuperUser

router = APIRouter(tags=["organizations"])


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: Optional[int] = Field(default=None)
    owner_login: Optional[str] = Field(default=None)


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)


class SuperuserRequest(BaseModel):
    is_superuser: bool


def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except organizations_api.OrganizationActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Администратор развёртывания ----------

@router.get("/admin/organizations")
def list_organizations(request: Request, who: SuperUser) -> dict[str, Any]:
    return organizations_api.list_organizations(request.app.state.repo)


@router.post("/admin/organizations")
def create_organization(body: CreateOrganizationRequest, request: Request,
                        who: SuperUser) -> dict[str, Any]:
    return _run(organizations_api.create_organization,
                request.app.state.repo, name=body.name,
                parent_id=body.parent_id, owner_login=body.owner_login)


@router.patch("/admin/organizations/{org_id}")
def rename_organization(org_id: int, body: RenameRequest, request: Request,
                        who: SuperUser) -> dict[str, Any]:
    return _run(organizations_api.rename_organization,
                request.app.state.repo, org_id=org_id, name=body.name)


@router.post("/admin/superusers/{login}")
def set_superuser(login: str, body: SuperuserRequest, request: Request,
                  who: SuperUser) -> dict[str, Any]:
    return _run(organizations_api.set_superuser, request.app.state.repo,
                actor_login=who.login, target_login=login,
                value=body.is_superuser)


# ---------- Админ организации ----------

@router.get("/admin/organizations/{org_id}")
def get_organization(org_id: int, request: Request,
                     who: AdminUser) -> dict[str, Any]:
    """Чужую организацию не видно вовсе (§8.1) — 404, а не 403: «есть, но
    не для вас» перебором id выдаёт, какие организации существуют."""
    if not who.is_superuser and who.organization_id != org_id:
        raise HTTPException(status_code=404,
                            detail=f"Организация #{org_id} не найдена.")
    return _run(organizations_api.get_organization,
                request.app.state.repo, org_id)


@router.post("/admin/organizations/{org_id}/members")
def add_member(org_id: int, body: LoginRequest, request: Request,
               who: AdminUser) -> dict[str, Any]:
    """Приём в организацию. Принимать в ЧУЖУЮ нельзя — иначе админ кафедры
    перетаскивал бы к себе людей соседней."""
    if not who.is_superuser and who.organization_id != org_id:
        raise HTTPException(status_code=403,
                            detail="Принимать можно только в свою организацию.")
    return _run(organizations_api.move_user, request.app.state.repo,
                login=body.login, org_id=org_id)


@router.delete("/admin/organizations/{org_id}/members/{login}")
def remove_member(org_id: int, login: str, request: Request,
                  who: AdminUser) -> dict[str, Any]:
    if not who.is_superuser and who.organization_id != org_id:
        raise HTTPException(status_code=403,
                            detail="Исключать можно только из своей организации.")
    return _run(organizations_api.move_user, request.app.state.repo,
                login=login, org_id=None)


@router.post("/admin/organizations/{org_id}/owner")
def transfer_ownership(org_id: int, body: LoginRequest, request: Request,
                       who: AdminUser) -> dict[str, Any]:
    return _run(organizations_api.transfer_ownership, request.app.state.repo,
                org_id=org_id, new_owner=body.login, actor_login=who.login,
                actor_is_superuser=who.is_superuser)


# ---------- Своя организация ----------

@router.get("/organizations/mine")
def my_organization(request: Request, who: CurrentUser) -> dict[str, Any]:
    """Кто я и где состою. Нужна фронту и десктопу, чтобы показывать
    принадлежность, а не догадываться о ней."""
    repo = request.app.state.repo
    org = (repo.get_organization(who.organization_id)
           if who.organization_id is not None else None)
    return {"login": who.login, "role": who.role,
            "is_superuser": who.is_superuser,
            "organization": org,
            "is_owner": bool(org and org["owner_login"] == who.login)}
