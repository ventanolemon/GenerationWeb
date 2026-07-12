"""
ContextVar'ы личности текущего HTTP-запроса — тот же паттерн, что
generator_service/context.py (см. rbac_and_data_model.md §3: enforcement
живёт в web_layer, внутрь приватной сети личность пробрасывается
заголовками X-User-Id / X-User-Role, сервис им доверяет).
"""

from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

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
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: str = Header(default="student"),
) -> Identity:
    """FastAPI-зависимость: личность из заголовков web_layer.

    Возвращает Identity — хендлеры читают роль из него (sync-зависимости и
    sync-эндпоинты FastAPI исполняет в разных threadpool-контекстах, поэтому
    ContextVar между ними НЕ переживает; переменные ниже выставляются для
    глубинных слоёв, вызываемых из самого хендлера). 401 — если web_layer
    не проставил личность.

    user_id — логин-строка (X-User-Id), а не число: раньше здесь стоял
    int(x_user_id) и десктоп с логином получал 401 «должен быть числом»."""
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    ident = Identity(user_id=uid, role=x_user_role.strip().lower() or "student")
    current_user_id.set(ident.user_id)
    current_user_role.set(ident.role)
    return ident
