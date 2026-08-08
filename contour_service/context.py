"""
ContextVar'ы личности текущего HTTP-запроса.

Раньше здесь было написано, что enforcement живёт в web_layer, а сервис
доверяет заголовкам X-User-Id / X-User-Role. Первое оказалось неверным
(во всём web_layer нет ни одного сравнения роли), а второе — опасным:
заголовки пишет браузер, и на роли здесь завязано, кто видит и утверждает
ЧУЖИЕ джобы. Достаточно было послать X-User-Role: admin.

Теперь личность заверяет токен сессии, а роль сервис читает из БД —
той же, что у генератора (`app.state.repo`). Правило одно на оба сервиса
и живёт в `core.auth_sessions.resolve_identity`: держи его в одном —
и снятие доверия к заголовкам закрыло бы дыру только там.
"""

from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request

from core import auth_sessions

current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id", default=None
)
current_user_role: ContextVar[str] = ContextVar(
    "current_user_role", default="student"
)


@dataclass(frozen=True)
class Identity:
    """Личность запроса из заголовков web_layer. user_id — логин-строка
    (канонический id, единый с десктопом core.session.Session и sync-путём)."""
    user_id: str
    role: str


def require_identity(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> Identity:
    """FastAPI-зависимость: заверенная личность запроса.

    Возвращает Identity — хендлеры читают роль из него (sync-зависимости и
    sync-эндпоинты FastAPI исполняет в разных threadpool-контекстах, поэтому
    ContextVar между ними НЕ переживает; переменные ниже выставляются для
    глубинных слоёв, вызываемых из самого хендлера). 401 — если личности
    нет или она недействительна.

    user_id — логин-строка, а не число: раньше здесь стоял int(x_user_id)
    и десктоп с логином получал 401 «должен быть числом»."""
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=401,
                            detail="Сервис не готов проверять личность.")
    try:
        who = auth_sessions.resolve_identity(
            repo, authorization, x_user_id, x_user_role)
    except auth_sessions.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    if who is None:
        raise HTTPException(
            status_code=401,
            detail="Нужен вход: заголовок Authorization: Bearer <токен>.")
    ident = Identity(user_id=who.login, role=who.role)
    current_user_id.set(ident.user_id)
    current_user_role.set(ident.role)
    return ident
