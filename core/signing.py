"""
Общий корень доверия: канонизация манифестов и проверка подписи Ed25519.

Один модуль на всё, что сервер РАЗДАЁТ, но не производит: обновления
приложения (`core/updates.py`) и пакеты узлов (`core/node_packages.py`).
Это не экономия строк — это то, ради чего пакеты вообще можно разрешить.

Докачка узлов с сервера была бы новым каналом доставки исполняемого кода на
чужие машины, если бы у неё была своя, отдельная схема доверия. С общим
корнем она — тот же самый канал, что и обновление приложения, только мельче
гранулярностью: тот же офлайновый ключ, та же проверка на клиенте, та же
защита от отката. Новых способов чему-то доверять не появляется.

Правила, одинаковые для обоих:

* **Подписывает не сервер.** Приватного ключа здесь нет; сервер принимает
  уже подписанное, проверяет и хранит.
* **Подписан манифест целиком**, а не хеш артефакта. Подпись одного лишь
  хеша позволила бы переклеить честно подписанный файл под другое имя,
  версию или платформу, не трогая подпись.
* **Канонизация одной функцией.** Подписывающая и проверяющие стороны
  обязаны получать байт в байт одно и то же; расхождение даёт не «подпись
  не сошлась по делу», а ложную тревогу, которую потом ищут часами.
* **Ed25519.** Короткие ключи и подписи, нет параметров, которые можно
  выбрать неправильно (в отличие от RSA с паддингами и размерами). Для
  канала доставки кода это важнее скорости.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Iterable


class SignatureError(ValueError):
    """Подпись не сошлась, не разбирается или проверить её нечем."""


def canonical_manifest(payload: dict, fields: Iterable[str],
                       int_fields: Iterable[str] = ()) -> bytes:
    """
    Байты, которые подписывают и проверяют.

    `fields` задаёт СОСТАВ подписанного — добавишь поле, и все ранее
    выпущенные подписи перестанут сходиться. Порядок не важен: ключи
    сортируются.

    Типы приводятся явно (`int_fields` — к целому, остальное к строке),
    потому что источники разные: подписывающий скрипт читает из argparse,
    сервер — из JSON-тела, клиент — из ответа API. `1` и `"1"` обязаны
    давать одинаковые байты, иначе подпись «то сходится, то нет».
    """
    int_fields = set(int_fields)
    canonical = {}
    for field in fields:
        value = payload.get(field)
        canonical[field] = (int(value or 0) if field in int_fields
                            else str(value or ""))
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def verify(manifest_bytes: bytes, signature_b64: str,
           public_key_b64: str) -> None:
    """Проверить подпись канонического манифеста. Бросает SignatureError."""
    if not public_key_b64.strip():
        raise SignatureError(
            "Публичный ключ не настроен — принять подписанное содержимое, "
            "не имея чем проверить подпись, нельзя.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
    except ImportError as exc:                       # pragma: no cover
        raise SignatureError(
            "Нет библиотеки cryptography — проверить подпись невозможно. "
            "Принимать без проверки нельзя.") from exc

    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"Ключ или подпись не разбираются: {exc}") from exc

    try:
        key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise SignatureError(
            "Подпись не соответствует манифесту. Содержимое или его описание "
            "изменены после подписания — принимать нельзя.") from exc


def key_fingerprint(public_key_b64: str) -> str:
    """Короткий отпечаток ключа для сверки глазами (ops), не для проверок."""
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, ValueError):
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]
