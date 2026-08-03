"""
Обновление десктопного приложения.

  GET  /updates/check              что клиенту делать (identity не нужна)
  GET  /updates/key                отпечаток ключа выпуска (диагностика)
  GET  /admin/releases             история выпусков (admin)
  POST /admin/releases             опубликовать подписанный релиз (admin)
  POST /admin/releases/{v}/yank    отозвать (admin)

Публичный ключ берётся из окружения `RELEASE_PUBLIC_KEY` (base64 сырых
32 байт Ed25519). Приватного ключа на сервере НЕТ и быть не должно:
подпись делается офлайн (`scripts/sign_release.py`), иначе взлом раздающей
машины означал бы возможность подписать что угодно и разослать на все
десктопы.

`/updates/check` намеренно без авторизации. Обновление безопасности должно
доезжать и до того, у кого протух токен или кого выгнали из системы; а
скрывать факт существования версии смысла нет — она и так у всех на
машинах. Подлинность обеспечивает подпись, а не закрытость эндпоинта.

Ключ через эндпоинт НЕ раздаётся. Клиент, который берёт ключ у того же
сервера, что и обновление, не проверяет ничего: подменивший сервер подменит
и ключ. Ключ клиент носит с собой; наружу отдаётся только отпечаток, чтобы
администратор мог глазами сверить, тем ли ключом сервер проверяет.
"""

from __future__ import annotations
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import signing, signing_keys, updates

router = APIRouter(tags=["updates"])


def _public_key() -> str:
    return os.environ.get("RELEASE_PUBLIC_KEY", "").strip()


class RotateKeysRequest(BaseModel):
    payload: str = Field(..., min_length=2,
                         description="канонический набор, ровно как подписан")
    signature: str = Field(..., min_length=1,
                           description="подпись ДЕЙСТВУЮЩИМ ключом")
    new_key_signature: str = Field(
        default="", description="со-подпись новым ключом: доказательство "
                                "владения приватной частью")


class PublishRequest(BaseModel):
    version: str = Field(..., min_length=1)
    channel: str = Field(default="stable")
    platform: str = Field(default="any")
    sequence: int = Field(..., ge=1,
                          description="монотонный счётчик выпуска; "
                                      "входит в подписанный манифест")
    url: str = Field(..., min_length=1)
    size_bytes: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=64, max_length=64)
    signature: str = Field(..., min_length=1,
                           description="base64 Ed25519 подписи манифеста")
    signing_key_id: str = Field(default="")
    min_supported: str = Field(default="", description="ниже — обязательное")
    notes: str = Field(default="")


def _require_admin(x_user_id: Optional[str], x_user_role: Optional[str]) -> str:
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    if (x_user_role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403,
                            detail="Доступно только администратору.")
    return uid


def _run(fn, *args, **kwargs) -> Any:
    # SignatureError живёт в общем core/signing.py и не наследует UpdateError:
    # он общий с пакетами узлов. Смысл для HTTP у обоих один — «вход не
    # годится», то есть 400, а не 500: сервер исправен, негоден запрос.
    try:
        return fn(*args, **kwargs)
    except (updates.UpdateError, signing_keys.KeyRotationError,
            signing.SignatureError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/updates/check")
def get_check(
    request: Request,
    current_version: str = Query(default="", description="что стоит сейчас"),
    current_sequence: int = Query(default=0, ge=0,
                                  description="счётчик установленного"),
    channel: str = Query(default="stable"),
    platform: str = Query(default="any"),
) -> dict[str, Any]:
    """
    Ответ самодостаточен: манифест и подпись внутри. Клиент обязан проверить
    подпись СВОИМ ключом до записи файла на диск и отвергнуть всё, у чего
    `sequence` не больше установленного, — сервер здесь не граница
    безопасности, а источник данных.
    """
    return _run(updates.check, request.app.state.repo,
                current_version=current_version,
                current_sequence=current_sequence,
                channel=channel, platform=platform)


@router.get("/updates/key")
def get_key_fingerprint(request: Request) -> dict[str, Any]:
    """Отпечатки действующих ключей — для сверки глазами. Сами ключи здесь
    не отдаются: клиент, берущий ключ у того же сервера, что и обновление,
    не проверяет ничего."""
    repo = request.app.state.repo
    signing_keys.ensure_bootstrapped(repo, _public_key())
    keyset = signing_keys.current_keyset(repo)
    if keyset is None:
        return {"configured": False, "fingerprints": []}
    return {"configured": True, "sequence": keyset["sequence"],
            "fingerprints": [k["id"] for k in keyset["keys"]
                             if k["status"] == "active"]}


@router.get("/updates/keys")
def get_key_set(request: Request) -> dict[str, Any]:
    """
    Действующий НАБОР ключей — подписанным артефактом, теми же байтами, что
    подписывали. Клиент принимает его, только если подпись сделана ключом,
    активным в наборе, которому он уже верит; так доверие переносится по
    цепочке и смена ключа не требует переустановки.

    Без авторизации по той же причине, что и /updates/check: клиент со
    старым набором обязан суметь догнать ротацию, даже если его токен протух.
    """
    repo = request.app.state.repo
    signing_keys.ensure_bootstrapped(repo, _public_key())
    return signing_keys.key_set_response(repo)


@router.post("/admin/signing-keys/rotate")
def post_rotate_keys(
    body: RotateKeysRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """
    Принять новый набор ключей. Сервер и здесь не подписывает — набор
    готовится офлайн (`scripts/sign_release.py rotate`).

    ВАЖНО: ротация по цепочке закрывает плановую смену и потерю ключа, но НЕ
    компрометацию — укравший приватный ключ подпишет ротацию на свой, и
    подпись будет валидной. От этого спасает только доставка набора вне
    канала (новая сборка). См. app_updates.md.
    """
    actor = _require_admin(x_user_id, x_user_role)
    repo = request.app.state.repo
    signing_keys.ensure_bootstrapped(repo, _public_key())
    return _run(signing_keys.rotate, repo, payload=body.payload,
                signature=body.signature,
                new_key_signature=body.new_key_signature, actor_login=actor)


@router.get("/admin/signing-keys")
def get_key_history(
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return signing_keys.history(request.app.state.repo)


@router.get("/admin/releases")
def get_history(
    request: Request,
    channel: Optional[str] = Query(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_admin(x_user_id, x_user_role)
    return updates.history(request.app.state.repo, channel=channel)


@router.post("/admin/releases")
def post_publish(
    body: PublishRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Сервер проверяет подпись и сохраняет. Не подписывает."""
    actor = _require_admin(x_user_id, x_user_role)
    return _run(updates.publish, request.app.state.repo,
                version=body.version, channel=body.channel,
                platform=body.platform, sequence=body.sequence,
                url=body.url,
                size_bytes=body.size_bytes, sha256=body.sha256,
                signature=body.signature, public_key=_public_key(),
                signing_key_id=body.signing_key_id,
                min_supported=body.min_supported, notes=body.notes,
                actor_login=actor)


@router.post("/admin/releases/{version}/yank")
def post_yank(
    version: str,
    request: Request,
    channel: str = Query(default="stable"),
    platform: str = Query(default="any"),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Перестать предлагать релиз. Уже установленное не откатывается — откат
    по команде сервера был бы ещё одним способом навязать клиенту чужой
    выбор; для этого выпускают новую версию."""
    _require_admin(x_user_id, x_user_role)
    return _run(updates.yank, request.app.state.repo, version=version,
                channel=channel, platform=platform)
