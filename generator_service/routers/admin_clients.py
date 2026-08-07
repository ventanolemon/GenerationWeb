"""
Управление клиентами публичного API (admin-only).

  GET    /admin/api-clients                    список приложений
  POST   /admin/api-clients                    завести приложение
  GET    /admin/api-clients/{id}               одно приложение
  DELETE /admin/api-clients/{id}               удалить вместе с ключами
  POST   /admin/api-clients/{id}/keys          выпустить ключ (открытый — раз)
  DELETE /admin/api-clients/{id}/keys/{prefix} отозвать ключ
  PUT    /admin/api-clients/{id}/subjects      скоуп контента
  PUT    /admin/api-clients/{id}/quota         суточная квота
  PUT    /admin/api-clients/{id}/status        active|suspended

Кто заводит ключи — админ, как и всё остальное административное в этом
сервисе (`/admin/users`, `/admin/groups`, `/admin/subject-grants`).
Самообслуживание разработчиков (консоль, регистрация приложений) — часть
этапа 5 из public_api.md и отдельное продуктовое решение; до него раздача
ключей руками админа не мешает ничему, а лишнюю поверхность не открывает.

Логика — core/api_clients.py (headless), роутер адаптирует HTTP.
"""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import api_clients

from ..identity import AdminUser

router = APIRouter(prefix="/admin/api-clients", tags=["admin"])


class CreateClientRequest(BaseModel):
    name: str = Field(..., min_length=1)
    daily_quota: int = Field(default=api_clients.DEFAULT_DAILY_QUOTA, ge=0)


class IssueKeyRequest(BaseModel):
    kind: str = Field(default="server", description="server | browser")
    allowed_origins: str = Field(
        default="", description="Через запятую; обязателен для browser")


class SubjectsRequest(BaseModel):
    subject_ids: list[int] = Field(default_factory=list)


class QuotaRequest(BaseModel):
    daily_quota: int = Field(..., ge=0)


class StatusRequest(BaseModel):
    status: str = Field(..., description="active | suspended")



def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except api_clients.ApiClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_clients(
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return {"clients": api_clients.list_clients(request.app.state.repo)}


@router.post("")
def create_client(
    body: CreateClientRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.create_client, request.app.state.repo,
                name=body.name, owner_login=who.login,
                daily_quota=body.daily_quota)


@router.get("/{client_id}")
def get_client(
    client_id: int,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.describe_client, request.app.state.repo, client_id)


@router.delete("/{client_id}")
def delete_client(
    client_id: int,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.delete_client, request.app.state.repo,
                client_id=client_id)


@router.post("/{client_id}/keys")
def issue_key(
    client_id: int,
    body: IssueKeyRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Открытое значение ключа возвращается ЕДИНСТВЕННЫЙ раз — дальше в базе
    только хэш. Потерян — выпустите новый и отзовите старый."""
    return _run(api_clients.issue_key, request.app.state.repo,
                client_id=client_id, kind=body.kind,
                allowed_origins=body.allowed_origins)


@router.delete("/{client_id}/keys/{prefix}")
def revoke_key(
    client_id: int,
    prefix: str,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.revoke_key, request.app.state.repo,
                client_id=client_id, prefix=prefix)


@router.put("/{client_id}/subjects")
def set_subjects(
    client_id: int,
    body: SubjectsRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Пустой список = клиенту доступны все встроенные предметы и только они
    (авторский контент наружу без явного решения не уходит)."""
    return _run(api_clients.set_subjects, request.app.state.repo,
                client_id=client_id, subject_ids=body.subject_ids)


@router.put("/{client_id}/quota")
def set_quota(
    client_id: int,
    body: QuotaRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.set_quota, request.app.state.repo,
                client_id=client_id, daily_quota=body.daily_quota)


@router.put("/{client_id}/status")
def set_status(
    client_id: int,
    body: StatusRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(api_clients.set_status, request.app.state.repo,
                client_id=client_id, status=body.status)
