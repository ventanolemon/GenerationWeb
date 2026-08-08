"""
Кто выполняет запрос — один ответ на весь сервис.

До этого модуля ответов было тринадцать: `_require_admin` был объявлен в
семи роутерах, `_identity` — в шести, и копии разошлись. Умолчание роли
при отсутствующем заголовке было разным в разных файлах (`""`, `student`,
`teacher`), причём вариант `teacher` открывал запись: студент получал её,
УБРАВ `X-User-Role` (см. organizations_readiness.md §3.2). Это не стиль —
это тринадцать мест, которые §8.2 плана пришлось бы править синхронно.

Здесь один резолвер и один гейт.

**Заголовкам больше не верят.** `GEN_TRUST_IDENTITY_HEADERS` выключен по
умолчанию: личность заверяет токен, роль сервер читает у себя в БД.
Флаг остался переходным средством для развёртывания, где ещё не обновили
десктопы, — включать осознанно и ненадолго.

Само правило разрешения живёт в `core/auth_sessions.resolve_identity`, а
не здесь: сервисов два (генератор и контур), они ходят в одну БД и оба
принимают личность от web_layer. Держи правило в одном из них — и снятие
доверия закрыло бы дыру только у него. Здесь остались адаптеры: перевод
отказа в HTTP-статус и зависимости FastAPI.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request

from core import auth_sessions
from core.auth_sessions import Identity

#: Переэкспорт: роутеры и тесты спрашивают про доверие заголовкам здесь,
#: а решает core — один ответ на оба сервиса.
trust_headers = auth_sessions.trust_headers


def resolve(request: Request, authorization: Optional[str] = None,
            x_user_id: Optional[str] = None,
            x_user_role: Optional[str] = None) -> Optional[Identity]:
    """Личность запроса или None. Правило — в core, здесь только перевод
    отказа в HTTP-статус."""
    try:
        return auth_sessions.resolve_identity(
            request.app.state.repo, authorization, x_user_id, x_user_role)
    except auth_sessions.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


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
# Ровно на этом разъехались четырнадцать прежних копий.
#
# Это ТОНКИЕ адаптеры: решение принимают resolve/require/require_admin
# выше. Заводить здесь вторую реализацию тех же правил значило бы начать
# ту же историю заново.

def _headers(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Optional[Identity]:
    return resolve(request, authorization, x_user_id, x_user_role)


def _required(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Identity:
    return require(request, authorization, x_user_id, x_user_role)


def require_superuser(request: Request, authorization: Optional[str] = None,
                      x_user_id: Optional[str] = None,
                      x_user_role: Optional[str] = None) -> Identity:
    """
    Гейт администратора РАЗВЁРТЫВАНИЯ.

    Отдельно от `require_admin`, потому что это другая ось (§8.2): `admin`
    после введения организаций означает «админ своей организации», а
    пакеты узлов, ключи подписи, выпуски и публичный API остаются решением
    уровня развёртывания. Набор установленных пакетов один на всех — иначе
    вопрос «какой код здесь исполняется» переходит к организации.
    """
    who = require(request, authorization, x_user_id, x_user_role)
    if not who.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Доступно только администратору развёртывания.")
    return who


def _superuser(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Identity:
    return require_superuser(request, authorization, x_user_id, x_user_role)


def _admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Identity:
    return require_admin(request, authorization, x_user_id, x_user_role)


def actor(who: Optional[Identity]) -> tuple[Optional[str], str]:
    """
    Личность → `(логин или None, роль)` для ручек, открытых гостю.

    У гостя роль — самая строгая, а не «удобная». Ровно на этом разъехались
    прежние копии: `sync.py` подставлял `teacher`, и запись открывалась
    тому, кто просто не прислал заголовок.
    """
    return ((who.login, who.role) if who
            else (None, auth_sessions.STRICTEST_ROLE))


#: Личность, если она есть; None у гостя. Для ручек, которые гостю открыты.
MaybeUser = Annotated[Optional[Identity], Depends(_headers)]
#: Личность обязательна — иначе 401.
CurrentUser = Annotated[Identity, Depends(_required)]
#: Личность обязательна и роль — admin (в СВОЕЙ организации), иначе 403.
AdminUser = Annotated[Identity, Depends(_admin)]
#: Администратор развёртывания: пакеты, ключи, выпуски, публичный API.
SuperUser = Annotated[Identity, Depends(_superuser)]


__all__ = ["Identity", "resolve", "require", "require_admin",
           "require_superuser", "trust_headers", "actor",
           "MaybeUser", "CurrentUser", "AdminUser", "SuperUser"]
