"""
Клиенты публичного API: ключи, скоуп контента, квоты.

Реализует этапы 1–2 из docs/architecture/public_api.md. Субъект здесь —
ПРИЛОЖЕНИЕ, а не человек: у ключа нет роли и профиля, у него есть владелец,
набор доступных предметов и суточный лимит вызовов.

Чистая логика (headless, как grants/admin/sync_api) — роутеры
`generator_service/routers/public_v1.py` и `.../admin_clients.py` только
адаптируют HTTP.

## Ключ

Формат `gw_<kind>_<43 симв. base64url>` — 256 бит случайности из
`secrets.token_urlsafe`. Префикс (`gw_live_A1b2c3d4`) хранится открытым
текстом и показывается владельцу в списке; сам ключ хранится sha256-хэшем и
после выдачи не восстановим — потерял, значит выпусти новый и отзови старый.

Быстрый хэш вместо pbkdf2, которым в этом же проекте хэшируются пароли, —
осознанно: пароль человек выбирает из крошечного словаря, и медленный KDF
покупает время против перебора; ключ — машинная случайность в 256 бит,
перебирать нечего ни за какое время. Зато проверка идёт на КАЖДОМ запросе
публичного API, и pbkdf2 здесь оплачивал бы несуществующую угрозу
задержкой ответа.

## Скоуп

Пустой набор явных выдач = клиенту доступны ВСЕ встроенные предметы
(`owner_user_id IS NULL`) и только они. Это безопасный старт из §8
документа: встроенные принадлежат самому продукту, авторский контент —
преподавателям, и наружу он без явного решения администратора не уходит.
Явные выдачи набор сужают или расширяют — ровно как `subject_grants` у
преподавателя, тот же механизм с другим субъектом.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from .repository import Repository

KEY_KINDS = ("server", "browser")
CLIENT_STATUSES = ("active", "suspended")
DEFAULT_DAILY_QUOTA = 1000
# Длина видимого префикса после `gw_<kind>_`: достаточно, чтобы владелец
# отличил свои ключи друг от друга, и мало, чтобы это не помогало перебору.
_PREFIX_CHARS = 8


class ApiClientError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


class ApiAuthError(Exception):
    """Ключ не принят. `status` — какой ответ отдать (401/403/429)."""

    def __init__(self, message: str, status: int = 401, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


# ---------- Ключи ----------

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _today() -> str:
    """Сутки квоты — UTC, а не локальные: сервер и клиент живут в разных
    поясах, и «день» обязан быть одним и тем же по обе стороны."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def issue_key(repo: Repository, *, client_id: int, kind: str = "server",
              allowed_origins: str = "") -> dict:
    """
    Выпустить ключ. Открытое значение возвращается ЕДИНСТВЕННЫЙ раз —
    дальше в базе только хэш.
    """
    if kind not in KEY_KINDS:
        raise ApiClientError(f"kind: 'server'|'browser', не {kind!r}.")
    if repo.get_api_client(client_id) is None:
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    if kind == "browser" and not allowed_origins.strip():
        # Браузерный ключ лежит в исходнике страницы и секретом не является;
        # единственное, что его защищает, — привязка к origin. Ключ без неё
        # был бы просто публичной строкой, дающей полный доступ.
        raise ApiClientError(
            "Браузерному ключу обязателен allowed_origins: он публичен по "
            "своей природе, и origin — единственное, что его ограничивает.")

    raw = f"gw_{'live' if kind == 'server' else 'web'}_{secrets.token_urlsafe(32)}"
    prefix = raw[:raw.rindex("_") + 1 + _PREFIX_CHARS]
    repo.add_api_key(hash_key(raw), client_id, kind, prefix,
                     allowed_origins.strip())
    return {"key": raw, "prefix": prefix, "kind": kind,
            "allowed_origins": allowed_origins.strip()}


def authenticate(repo: Repository, raw_key: str,
                 origin: Optional[str] = None) -> dict:
    """
    Проверить ключ и вернуть его клиента. Бросает ApiAuthError.

    Порядок проверок — от самой дешёвой и самой частой к редким; отказ
    формулируется одинаково для «нет такого ключа» и «ключ отозван», чтобы
    перебор не отличал одно от другого.
    """
    raw = (raw_key or "").strip()
    if not raw:
        raise ApiAuthError("Нужен заголовок Authorization: Bearer <ключ>.")
    row = repo.find_api_key(hash_key(raw))
    if row is None or row["revoked_at"] is not None:
        raise ApiAuthError("Ключ недействителен.")
    if row["client_status"] != "active":
        raise ApiAuthError("Доступ приложения приостановлен.", status=403)
    if row["kind"] == "browser":
        allowed = [o.strip() for o in (row["allowed_origins"] or "").split(",")
                   if o.strip()]
        if (origin or "").strip() not in allowed:
            raise ApiAuthError(
                f"Origin {origin or '—'} не разрешён для этого ключа.",
                status=403)
    return row


# ---------- Скоуп контента ----------

def client_subject_ids(repo: Repository, client_id: int) -> list[int]:
    """Предметы, доступные клиенту: явные выдачи либо все встроенные."""
    explicit = repo.api_client_subject_ids(client_id)
    return explicit if explicit else repo.builtin_subject_ids()


# ---------- Квота ----------

def check_and_count(repo: Repository, client: dict) -> dict:
    """
    Учесть тарифицируемый вызов. Бросает ApiAuthError(429) при исчерпании.

    Считаются только генерации: каталог и `/me` — дешёвые чтения, и брать за
    них квоту значило бы наказывать за аккуратную интеграцию, которая
    сверяется с каталогом перед запросом.

    Инкремент идёт ДО работы, а не после: иначе параллельные запросы успели
    бы проскочить лимит все разом. Цена — вызов, упавший по вине сервиса,
    остаётся в счётчике; это честнее противоположной ошибки.
    """
    quota = int(client.get("daily_quota") or 0)
    day = _today()
    used = repo.bump_api_usage(client["client_id"], day)
    if quota and used > quota:
        raise ApiAuthError(
            f"Суточная квота исчерпана: {quota} вызовов.", status=429)
    return {"used": used, "quota": quota, "day": day}


def usage_snapshot(repo: Repository, client: dict) -> dict:
    day = _today()
    return {"used": repo.api_usage(client["client_id"], day),
            "quota": int(client.get("daily_quota") or 0), "day": day}


# ---------- Администрирование ----------

def create_client(repo: Repository, *, name: str, owner_login: Optional[str],
                  daily_quota: int = DEFAULT_DAILY_QUOTA) -> dict:
    name = (name or "").strip()
    if not name:
        raise ApiClientError("Имя приложения не может быть пустым.")
    if int(daily_quota) < 0:
        raise ApiClientError("Квота не может быть отрицательной.")
    client_id = repo.create_api_client(name, owner_login, int(daily_quota))
    return describe_client(repo, client_id)


def describe_client(repo: Repository, client_id: int) -> dict:
    client = repo.get_api_client(client_id)
    if client is None:
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    client["keys"] = repo.list_api_keys(client_id)
    client["subject_ids"] = repo.api_client_subject_ids(client_id)
    client["usage"] = {"day": _today(),
                       "used": repo.api_usage(client_id, _today())}
    return client


def list_clients(repo: Repository) -> list[dict]:
    return [describe_client(repo, c["id"]) for c in repo.list_api_clients()]


def set_status(repo: Repository, *, client_id: int, status: str) -> dict:
    if status not in CLIENT_STATUSES:
        raise ApiClientError(
            f"status: 'active'|'suspended', не {status!r}.")
    if not repo.set_api_client_status(client_id, status):
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    return describe_client(repo, client_id)


def set_quota(repo: Repository, *, client_id: int, daily_quota: int) -> dict:
    if int(daily_quota) < 0:
        raise ApiClientError("Квота не может быть отрицательной.")
    if not repo.set_api_client_quota(client_id, int(daily_quota)):
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    return describe_client(repo, client_id)


def set_subjects(repo: Repository, *, client_id: int, subject_ids) -> dict:
    if repo.get_api_client(client_id) is None:
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    try:
        ids = sorted({int(s) for s in subject_ids})
    except (TypeError, ValueError) as exc:
        raise ApiClientError("subject_ids: список целых id.") from exc
    known = {s.id for s in repo.list_subjects()}
    unknown = [s for s in ids if s not in known]
    if unknown:
        raise ApiClientError(
            f"Неизвестные предметы: {', '.join(str(s) for s in unknown)}.")
    repo.replace_api_client_subjects(client_id, ids)
    return describe_client(repo, client_id)


def revoke_key(repo: Repository, *, client_id: int, prefix: str) -> dict:
    if not repo.revoke_api_key(client_id, prefix):
        raise ApiClientError(
            f"Действующий ключ с префиксом {prefix!r} не найден.")
    return describe_client(repo, client_id)


def delete_client(repo: Repository, *, client_id: int) -> dict:
    """Клиент удаляется вместе с ключами и выдачами (ON DELETE CASCADE)."""
    if repo.get_api_client(client_id) is None:
        raise ApiClientError(f"Клиент #{client_id} не найден.")
    with repo._connect() as conn:  # noqa: SLF001 — слой данных
        conn.execute("DELETE FROM api_clients WHERE id = ?", (client_id,))
        conn.commit()
    return {"deleted": client_id, "at": time.time()}
