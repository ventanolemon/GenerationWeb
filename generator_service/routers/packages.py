"""
Пакеты узлов графа.

  GET    /packages                      каталог: что есть и что установлено
  GET    /packages/{name}/manifest      манифест + подпись для установки
  GET    /admin/packages/requests       чего людям не хватает (admin)
  POST   /admin/packages                опубликовать подписанный пакет (admin)
  POST   /admin/packages/{name}/install разрешить на сервере (admin)
  DELETE /admin/packages/{name}/install убрать с сервера (admin)
  POST   /admin/packages/{name}/yank    отозвать версию (admin)

Канал ОДНОСТОРОННИЙ: пакеты приезжают с сервера, с десктопов наружу ничего
не публикуется. Публикация — админ плюс офлайновая подпись, тем же ключом и
той же механикой, что обновления приложения (`core/signing.py`).

Каталог и манифест доступны без авторизации по той же причине, что и
`/updates/check`: пакет нужен, чтобы граф вообще открылся, и запирать это за
токеном значит ломать работу тому, у кого он протух. Подлинность даёт
подпись, а не закрытость эндпоинта.
"""

from __future__ import annotations
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import node_packages, signing

from ..identity import AdminUser

router = APIRouter(tags=["packages"])


def _public_key() -> str:
    # Тот же ключ, что у релизов: один корень доверия на всё, что сервер
    # раздаёт, но не производит.
    return os.environ.get("RELEASE_PUBLIC_KEY", "").strip()


class PublishPackageRequest(BaseModel):
    name: str = Field(..., min_length=2)
    version: str = Field(..., min_length=1)
    sequence: int = Field(..., ge=1)
    url: str = Field(..., min_length=1)
    size_bytes: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=64, max_length=64)
    signature: str = Field(..., min_length=1)
    node_types: list[str] = Field(..., min_length=1,
                                  description="все с префиксом «имя.»")
    api_version: str = Field(default="1")
    signing_key_id: str = Field(default="")
    summary: str = Field(default="")


class InstallRequest(BaseModel):
    version: Optional[str] = Field(default=None,
                                   description="по умолчанию последняя")



def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except (node_packages.PackageError, signing.SignatureError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/packages")
def get_catalog(request: Request) -> dict[str, Any]:
    return node_packages.catalog(request.app.state.repo)


@router.get("/packages/{name}/manifest")
def get_manifest(
    name: str,
    request: Request,
    version: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Клиент обязан проверить подпись своим ключом ДО записи на диск и
    отвергнуть пакет, чей sequence не больше установленного."""
    return _run(node_packages.manifest_for_install, request.app.state.repo,
                name, version)


@router.post("/admin/packages")
def post_publish(
    body: PublishPackageRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(node_packages.publish, request.app.state.repo,
                name=body.name, version=body.version, sequence=body.sequence,
                url=body.url, size_bytes=body.size_bytes, sha256=body.sha256,
                signature=body.signature, node_types=body.node_types,
                public_key=_public_key(), api_version=body.api_version,
                signing_key_id=body.signing_key_id, summary=body.summary,
                actor_login=who.login)


@router.post("/admin/packages/{name}/install")
def post_install(
    name: str,
    body: InstallRequest,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Разрешить пакет на сервере. Это решение администратора о том, какой
    код здесь исполняется, — потому графы с неустановленными пакетами и
    отвергаются на push'е, а не тихо принимаются."""
    return _run(node_packages.install, request.app.state.repo, name=name,
                version=body.version, actor_login=who.login)


@router.delete("/admin/packages/{name}/install")
def delete_install(
    name: str,
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    return _run(node_packages.uninstall, request.app.state.repo, name=name)


@router.post("/admin/packages/{name}/yank")
def post_yank(
    name: str,
    request: Request,
    who: AdminUser,
    version: str = Query(...),
) -> dict[str, Any]:
    return _run(node_packages.yank, request.app.state.repo, name=name,
                version=version)


@router.get("/admin/packages/requests")
def get_requests(
    request: Request,
    who: AdminUser,
) -> dict[str, Any]:
    """Очередь «людям не хватает пакета X»: без неё отказ на push'е
    превращается в переписку в чате."""
    return node_packages.pending_requests(request.app.state.repo)
