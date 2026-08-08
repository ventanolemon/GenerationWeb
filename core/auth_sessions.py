"""
Сессии входа: заверенная идентичность.

До этого модуля личность приходила заголовками `X-User-Id`/`X-User-Role`,
которые пишет клиент. Замер перед §8 (`organizations_readiness.md`)
показал цену такой модели: преподаватель навсегда повышал студента до
админа, просто заявив о себе `X-User-Role: admin`, — и все 46 проверок
роли в коде опирались на эту строку.

Здесь личность становится ЗАВЕРЕННОЙ: вход по паролю выдаёт токен, а
дальше сервер по токену сам смотрит, кто это и какая у него роль.

**Почему непрозрачный токен, а не JWT.** У JWT одно настоящее
преимущество — проверка без обращения к хранилищу. Здесь оно не нужно
(запрос и так идёт в ту же БД за содержимым), а платить пришлось бы
отзывом: погасить выданный JWT нечем, кроме списка отозванных, то есть
того же обращения к хранилищу. Плюс роль внутри токена протухала бы —
понижение админа не действовало бы до конца его сессии.

**Роль не хранится в сессии вовсе.** Сессия знает только логин; роль
читается из `users` при каждом обращении (`find_auth_session` join'ит её).
Один источник правды — БД.

Токен хранится хэшем, как ключи приложений: утечка базы не должна давать
возможность войти. Открытое значение возвращается ровно один раз.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from .repository import Repository

#: Префикс — чтобы токен опознавался в логах и заголовках с одного взгляда.
_PREFIX = "gws_"

#: Сколько живёт сессия. Сутки по умолчанию: достаточно, чтобы не просить
#: пароль на каждом занятии, и мало, чтобы забытая вкладка не была вечной.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class AuthError(Exception):
    """Токен не принят. `status` — что отдать наружу."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Identity:
    """
    Кто выполняет запрос. Единственная форма ответа на этот вопрос.

    `login` и `role` берутся из БД, а не из запроса, — в этом весь смысл
    типа. Если где-то в коде Identity собирается из заголовков, это видно
    по вызову, а не спрятано в строковых параметрах.
    """
    login: str
    role: str
    #: Откуда взялась личность: "session" — заверена токеном, "header" —
    #: заявлена клиентом (переходный режим, см. generator_service/identity.py).
    source: str = "session"
    #: Организация, в которой человек состоит (§8). None — вне организаций:
    #: так выглядит исключённый, которого ещё никуда не приняли.
    organization_id: Optional[int] = None
    #: Администратор РАЗВЁРТЫВАНИЯ — пакеты узлов, ключи подписи, выпуски,
    #: публичный API. Ортогонален роли: `admin` теперь значит «админ своей
    #: организации», а решения уровня развёртывания остаются здесь (§8.2).
    is_superuser: bool = False

    @property
    def verified(self) -> bool:
        return self.source == "session"


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def ttl_seconds() -> int:
    """TTL сессии; настраивается через GEN_AUTH_TTL_SECONDS."""
    try:
        value = int(os.environ.get("GEN_AUTH_TTL_SECONDS",
                                   DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    return value if value > 0 else DEFAULT_TTL_SECONDS


def issue(repo: Repository, login: str, *, user_agent: str = "",
          ttl: Optional[int] = None) -> dict:
    """
    Выдать сессию вошедшему. Пароль проверяет ВЫЗЫВАЮЩИЙ.

    Разделено сознательно: проверка пароля живёт в `repo.find_user`
    (там же, где форматы хэшей и их обновление), а здесь — только выдача.
    Иначе этот модуль пришлось бы тащить за собой знание о паролях.
    """
    profile = repo.get_user_profile(login)
    if profile is None:
        raise AuthError(f"Пользователь {login!r} не найден.", status=404)
    raw = _PREFIX + secrets.token_urlsafe(32)
    expires_at = time.time() + (ttl if ttl is not None else ttl_seconds())
    repo.add_auth_session(hash_token(raw), profile.login,
                          expires_at=expires_at, user_agent=user_agent)
    return {"token": raw, "expires_at": expires_at,
            "login": profile.login, "role": profile.role}


def resolve(repo: Repository, raw_token: str) -> Identity:
    """
    Токен → кто это. Бросает AuthError.

    Отказ формулируется одинаково для «нет такого токена», «отозван» и
    «истёк»: иначе перебор отличал бы несуществующий токен от погашенного.
    """
    raw = (raw_token or "").strip()
    if not raw:
        raise AuthError("Нужен заголовок Authorization: Bearer <токен>.")
    row = repo.find_auth_session(hash_token(raw))
    if row is None or row["revoked_at"] is not None:
        raise AuthError("Сессия недействительна — войдите заново.")
    if row["expires_at"] <= time.time():
        raise AuthError("Сессия недействительна — войдите заново.")
    # Скользящее last_seen: отличить брошенную сессию от активной, не
    # продлевая её сверх expires_at.
    repo.touch_auth_session(row["token_hash"])
    return Identity(login=row["login"], role=row["role"], source="session",
                    organization_id=row.get("organization_id"),
                    is_superuser=bool(row.get("is_superuser")))


def bearer_token(header_value: Optional[str]) -> str:
    """`Authorization: Bearer xxx` → `xxx`. Чужая схема — пусто."""
    text = (header_value or "").strip()
    if not text:
        return ""
    parts = text.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def revoke(repo: Repository, raw_token: str) -> bool:
    """Выход. Идемпотентен: повторный выход — не ошибка."""
    raw = (raw_token or "").strip()
    if not raw:
        return False
    return repo.revoke_auth_session(hash_token(raw))


def revoke_all(repo: Repository, login: str) -> int:
    """Погасить все сессии пользователя. Зовётся при смене пароля."""
    return repo.revoke_auth_sessions_for(login)


__all__ = ["Identity", "AuthError", "issue", "resolve", "revoke",
           "revoke_all", "hash_token", "bearer_token", "ttl_seconds",
           "DEFAULT_TTL_SECONDS"]
