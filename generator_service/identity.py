"""
Кто выполняет запрос — один ответ на весь сервис.

До этого модуля ответов было тринадцать: `_require_admin` был объявлен в
семи роутерах, `_identity` — в шести, и копии разошлись. Умолчание роли
при отсутствующем заголовке было разным в разных файлах (`""`, `student`,
`teacher`), причём вариант `teacher` открывал запись: студент получал её,
УБРАВ `X-User-Role` (см. organizations_readiness.md §3.2). Это не стиль —
это тринадцать мест, которые §8.2 плана пришлось бы править синхронно.

Здесь один резолвер и один гейт.

**Переходный режим.** Заверенная личность (`Authorization: Bearer`)
вводится раньше, чем на неё переведены все клиенты — десктоп, web_layer и
фронт обновляются следующими шагами. Пока они не обновлены, заголовкам
`X-User-Id`/`X-User-Role` приходится доверять, и это включается флагом
`GEN_TRUST_IDENTITY_HEADERS` (по умолчанию ВКЛЮЧЁН, чтобы шаг не ломал
работающее развёртывание). Выключение флага — последний шаг работы по
идентичности; после него заголовки перестают что-либо значить.

Флаг существует, чтобы у дыры была одна видимая ручка, а не чтобы её
сохранить: `identity.source` всегда говорит, заверена личность или
заявлена, и это видно в тестах и в журнале.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request

from core import auth_sessions
from core.auth_sessions import Identity

log = logging.getLogger(__name__)

#: Самая строгая из настоящих ролей. Умолчание при неразобранной личности
#: обязано быть строгим: заголовок может не доехать, и «не доехал» не
#: должно означать «можно больше».
_STRICTEST_ROLE = "student"

_WARNED = False


def trust_headers() -> bool:
    """Доверять ли `X-User-Id`/`X-User-Role`. Переходный режим, см. модуль."""
    raw = os.environ.get("GEN_TRUST_IDENTITY_HEADERS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _warn_once() -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning(
            "Личность принята из заголовков X-User-Id/X-User-Role: их пишет "
            "клиент, и роль в них не заверена. Переходный режим — снимается "
            "GEN_TRUST_IDENTITY_HEADERS=0 после перевода клиентов на токены."
        )


def resolve(request: Request, authorization: Optional[str] = None,
            x_user_id: Optional[str] = None,
            x_user_role: Optional[str] = None) -> Optional[Identity]:
    """
    Личность запроса или None, если её нет.

    Порядок: сначала токен (заверенная), потом — если переходный режим не
    выключен — заголовки (заявленная). Токен, если он есть, ВСЕГДА главнее:
    иначе клиент, предъявивший настоящую сессию, мог бы дописать себе роль
    заголовком.
    """
    token = auth_sessions.bearer_token(authorization)
    if token:
        # Негодный токен — это отказ, а не повод откатиться к заголовкам:
        # молчаливый откат означал бы, что протухшая сессия даёт больше
        # прав, чем свежая.
        try:
            return auth_sessions.resolve(request.app.state.repo, token)
        except auth_sessions.AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))

    if not trust_headers():
        return None

    login = (x_user_id or "").strip()
    if not login:
        return None
    _warn_once()
    role = (x_user_role or "").strip().lower() or _STRICTEST_ROLE
    return Identity(login=login, role=role, source="header")


def require(request: Request, authorization: Optional[str] = None,
            x_user_id: Optional[str] = None,
            x_user_role: Optional[str] = None) -> Identity:
    """Личность обязательна. Нет — 401 («неизвестно кто»), не 403."""
    who = resolve(request, authorization, x_user_id, x_user_role)
    if who is None:
        raise HTTPException(
            status_code=401,
            detail="Нужен вход: заголовок Authorization: Bearer <токен>.")
    return who


def require_admin(request: Request, authorization: Optional[str] = None,
                  x_user_id: Optional[str] = None,
                  x_user_role: Optional[str] = None) -> Identity:
    """
    Гейт администратора — один на сервис.

    Возвращает Identity, а не логин: вызывающему почти всегда нужна и роль
    (её кладут в бизнес-операцию), а собирать её заново из заголовков —
    ровно то расхождение, ради устранения которого модуль и написан.
    """
    who = require(request, authorization, x_user_id, x_user_role)
    if who.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Доступно только администратору.")
    return who


# ---------- Зависимости FastAPI ----------
# Роутеру не нужно объявлять три заголовка в каждой ручке: чем реже
# личность собирается вручную, тем меньше мест, где она соберётся иначе.
# Ровно на этом разъехались тринадцать прежних копий.

def _headers(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Optional[Identity]:
    return resolve(request, authorization, x_user_id, x_user_role)


def _required(who: Optional[Identity] = Depends(_headers)) -> Identity:
    if who is None:
        raise HTTPException(
            status_code=401,
            detail="Нужен вход: заголовок Authorization: Bearer <токен>.")
    return who


def _admin(who: Identity = Depends(_required)) -> Identity:
    if who.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Доступно только администратору.")
    return who


def actor(who: Optional[Identity]) -> tuple[Optional[str], str]:
    """
    Личность → `(логин или None, роль)` для ручек, открытых гостю.

    У гостя роль — самая строгая, а не «удобная». Ровно на этом разъехались
    прежние копии: `sync.py` подставлял `teacher`, и запись открывалась
    тому, кто просто не прислал заголовок.
    """
    return (who.login, who.role) if who else (None, _STRICTEST_ROLE)


#: Личность, если она есть; None у гостя. Для ручек, которые гостю открыты.
MaybeUser = Annotated[Optional[Identity], Depends(_headers)]
#: Личность обязательна — иначе 401.
CurrentUser = Annotated[Identity, Depends(_required)]
#: Личность обязательна и роль — admin, иначе 403.
AdminUser = Annotated[Identity, Depends(_admin)]


__all__ = ["Identity", "resolve", "require", "require_admin", "trust_headers",
           "MaybeUser", "CurrentUser", "AdminUser"]
