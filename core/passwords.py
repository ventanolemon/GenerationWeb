"""
Хеширование паролей — format-tagged KDF со встроенным путём апгрейда.

История форматов в БД проекта:
  * plaintext        — старые десктопные аккаунты (пароль как есть);
  * sha256(login:password) — старые веб-регистрации (repository._hash_password);
  * pbkdf2_sha256    — текущий формат (этот модуль).

`verify_password` принимает все три и сообщает `needs_upgrade=True` для двух
устаревших — вызывающий код перехеширует пароль в pbkdf2 при первом успешном
входе (см. Repository.find_user). Так плейнтекст/несолёный sha256 вымываются
из БД по мере логинов, без принудительного сброса паролей.

Почему pbkdf2, а не argon2id (как в docs/architecture/rbac_and_data_model.md):
argon2-cffi недоступен в целевом окружении, а слой `core/` обязан работать
без внешних зависимостей (тот же код грузится и на десктопе). pbkdf2_hmac —
это настоящий KDF из stdlib с солью и настраиваемым числом итераций. Формат
хранения самоописателен (префикс алгоритма), поэтому argon2id позже
подключается за тем же интерфейсом без миграции данных: достаточно добавить
ветку в `verify_password` и сменить `hash_password`.
"""

from __future__ import annotations
import hashlib
import hmac
import os

# Идентификатор текущего алгоритма и его параметры.
_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16

# Префикс, которым помечены унаследованные (не-KDF) значения после миграции 001.
LEGACY_PREFIX = "legacy:"


def hash_password(password: str) -> str:
    """Захешировать пароль в формате `pbkdf2_sha256$iterations$salt_hex$hash_hex`."""
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _legacy_sha256(login: str, password: str) -> str:
    """Формат старых веб-регистраций: sha256("login:password")."""
    return hashlib.sha256(f"{login}:{password}".encode()).hexdigest()


def verify_password(stored: str, password: str, login: str) -> tuple[bool, bool]:
    """
    Проверить пароль против сохранённого значения.

    Возвращает (ok, needs_upgrade):
      * ok            — пароль верен;
      * needs_upgrade — пароль верен, но хранится в устаревшем формате и его
                        следует перехешировать в pbkdf2.
    """
    if not stored:
        return (False, False)

    if stored.startswith(_ALGO + "$"):
        try:
            _algo, iters_s, salt_hex, hash_hex = stored.split("$", 3)
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iters_s),
            )
            return (hmac.compare_digest(dk.hex(), hash_hex), False)
        except (ValueError, TypeError):
            return (False, False)

    # Унаследованные значения: с префиксом (после миграции) или без (на всякий
    # случай, если запись не прошла миграцию). В обоих случаях содержимое —
    # либо plaintext, либо sha256(login:password); пробуем оба варианта.
    value = stored[len(LEGACY_PREFIX):] if stored.startswith(LEGACY_PREFIX) else stored
    if hmac.compare_digest(value, password):
        return (True, True)
    if hmac.compare_digest(value, _legacy_sha256(login, password)):
        return (True, True)
    return (False, False)
