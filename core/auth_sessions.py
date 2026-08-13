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
import logging
import os
import secrets
import time
from dataclasses import dataclass, replace
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
    #: Настоящая роль из БД, когда включена ПРИМЕРКА (режим разработчика).
    #: None — примерки нет и `role` настоящая.
    #:
    #: Поле именно такое, а не «acting_role» рядом с настоящей ролью, и это
    #: главное решение примерки: `role` ВСЕГДА эффективная. Иначе каждая из
    #: двух с лишним десятков проверок роли обязана была бы помнить, какую
    #: из двух брать, и примерка показывала бы половину продукта чужими
    #: глазами, а половину — своими. Забытая проверка при таком устройстве
    #: даёт не дыру, а несовпадение: примерка идёт только ВНИЗ.
    true_role: Optional[str] = None

    @property
    def verified(self) -> bool:
        return self.source == "session"

    @property
    def trying_on(self) -> bool:
        """Роль примеряется — это не настоящий её носитель."""
        return self.true_role is not None


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


# ---------- Разрешение личности запроса ----------
#
# Живёт в core/, а не в одном из сервисов, потому что сервисов ДВА:
# generator_service и contour_service ходят в одну БД и оба принимают
# личность от web_layer. Пока правило было в генераторе, снятие доверия к
# заголовкам закрыло бы дыру только у него, а контур продолжал бы верить
# заголовку `X-User-Role` — а у него на роли завязано, кто видит и
# утверждает чужие джобы.

log = logging.getLogger(__name__)

#: Самая строгая из настоящих ролей. Умолчание при неразобранной личности
#: обязано быть строгим: заголовок может не доехать, и «не доехал» не
#: должно означать «можно больше».
STRICTEST_ROLE = "student"

_WARNED = False


def trust_headers() -> bool:
    """
    Доверять ли `X-User-Id`/`X-User-Role`.

    ПО УМОЛЧАНИЮ — НЕТ. Флаг остался переходным средством для развёртывания,
    где ещё не обновили десктопы: у старой сборки токена нет, и без
    послабления она разом потеряет запись в общий каталог. Включать его
    осознанно и ненадолго — пока он включён, роль приходит с чужих слов.
    """
    raw = os.environ.get("GEN_TRUST_IDENTITY_HEADERS", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _warn_once() -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning(
            "GEN_TRUST_IDENTITY_HEADERS включён: личность принимается из "
            "заголовков X-User-Id/X-User-Role, которые пишет клиент, и роль "
            "в них не заверена. Это переходный режим для необновлённых "
            "десктопов, а не рабочая настройка."
        )


def resolve_identity(repo: Repository, authorization: Optional[str] = None,
                     x_user_id: Optional[str] = None,
                     x_user_role: Optional[str] = None,
                     acting_role: Optional[str] = None) -> Optional[Identity]:
    """
    Личность запроса или None, если её нет. Бросает AuthError на негодном
    токене — переводить в HTTP-статус адаптеру сервиса.

    Токен, если он есть, ВСЕГДА главнее заголовков: иначе клиент,
    предъявивший настоящую сессию, мог бы дописать себе роль заголовком.
    Негодный токен — отказ, а не повод откатиться к заголовкам: молчаливый
    откат означал бы, что протухшая сессия даёт больше прав, чем свежая.

    `acting_role` — примерка роли (режим разработчика). Заголовку здесь
    верить МОЖНО, и это не противоречие с абзацем выше: личность по-прежнему
    заверяет токен, а заголовок лишь просит показать продукт чужими
    глазами — просьбу проверяет `try_on_role` по настоящей записи в БД.
    """
    token = bearer_token(authorization)
    if token:
        return try_on_role(resolve(repo, token), acting_role)

    if not trust_headers():
        return None

    login = (x_user_id or "").strip()
    if not login:
        return None
    _warn_once()
    role = (x_user_role or "").strip().lower() or STRICTEST_ROLE
    # Организацию и флаг администратора развёртывания клиент не заявляет
    # даже здесь: их читаем из БД.
    return try_on_role(
        Identity(login=login, role=role, source="header",
                 organization_id=repo.user_organization_id(login),
                 is_superuser=repo.is_superuser(login)),
        acting_role)


#: Роли от слабой к сильной. Порядок нужен ровно для одного правила:
#: примерять можно только роль НЕ СИЛЬНЕЕ своей.
ROLE_ORDER = ("student", "teacher", "admin")


def try_on_role(who: Identity, acting_role: Optional[str]) -> Identity:
    """
    Примерить роль: увидеть продукт глазами студента, не переставая быть
    собой.

    Три правила, и каждое отвечает на свой вопрос.

    КТО. Только администратор развёртывания (`is_superuser`). Не «админ
    организации»: примерка — инструмент того, кто продукт делает, а не
    того, кто им управляет.

    ЧТО. Только роль не сильнее собственной, и вместе с примеркой
    снимается `is_superuser`. Иначе «примерил студента» показывало бы
    студента, который при этом администрирует развёртывание, — то есть не
    показывало бы ничего.

    КЕМ ОСТАЁШЬСЯ. `login` не меняется НИКОГДА. Примерка — это другой
    взгляд, а не другой человек: всё, что запишется (попытки, правки,
    журнал), останется записанным на самого разработчика. Подмена логина
    дала бы возможность действовать от чужого имени, а это уже не отладка.
    """
    wanted = (acting_role or "").strip().lower()
    if not wanted:
        return who
    if not who.is_superuser:
        raise AuthError("Примерка роли доступна только разработчику.",
                        status=403)
    if wanted not in ROLE_ORDER:
        raise AuthError(
            f"Неизвестная роль {wanted!r}; допустимы "
            f"{', '.join(ROLE_ORDER)}.", status=400)
    own = who.role if who.role in ROLE_ORDER else ROLE_ORDER[-1]
    if ROLE_ORDER.index(wanted) > ROLE_ORDER.index(own):
        raise AuthError(
            f"Примерить можно только роль не сильнее своей: у вас "
            f"{own!r}, запрошена {wanted!r}.", status=403)
    return replace(who, role=wanted, true_role=who.role, is_superuser=False)


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


__all__ = ["Identity", "AuthError", "issue", "resolve", "resolve_identity",
           "try_on_role", "ROLE_ORDER",
           "revoke", "revoke_all", "hash_token", "bearer_token",
           "ttl_seconds", "trust_headers", "STRICTEST_ROLE",
           "DEFAULT_TTL_SECONDS"]
