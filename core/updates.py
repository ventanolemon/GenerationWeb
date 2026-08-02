"""
Обновление десктопного приложения: реестр релизов и проверка подлинности.

Это канал, по которому на машины пользователей приезжает исполняемый код.
Поэтому решения здесь принимались от модели угроз, а не от удобства.

## Что кому не доверяем

**Сервер не подписывает.** Он хранит и раздаёт уже подписанное; приватного
ключа на нём нет. Иначе взлом раздающей машины = возможность подписать
что угодно и разослать это на все десктопы разом. Подпись делается офлайн
(`scripts/sign_release.py`), ключ живёт у выпускающего.

**HTTPS недостаточно.** Он защищает канал, но сам сервер — в модели угроз.
Подлинность даёт только подпись, проверяемая клиентом по ключу, который
клиент носит с собой.

**Хеш ≠ подпись.** `sha256` отвечает на «не побился ли файл при
скачивании», подпись — на «тот ли его выпустил». Подменивший файл подменит
и хеш; это разные свойства, и одно другое не заменяет.

## Что именно подписано

Подпись покрывает КАНОНИЧЕСКИЙ МАНИФЕСТ целиком, а не только хеш файла:
версия, канал, платформа, размер, sha256, sequence. Подпись одного лишь
хеша позволила бы переклеить честно подписанный артефакт под другую версию
или другую платформу, не трогая подпись, — то есть выдать старую сборку за
новую.

Канонизация — JSON с сортированными ключами, без пробелов, UTF-8. Формат
зафиксирован: изменишь сериализацию — сломаешь все ранее выпущенные
подписи.

## Откат

Подсунуть СТАРЫЙ, честно подписанный релиз с уже известной дырой — рабочая
атака, и подпись от неё не защищает: она валидна. Защищает монотонный
`sequence`: клиент отвергает всё, у чего он не больше установленного.
Именно `sequence`, а не версия: сравнение semver — это разбор строки, на
котором легко ошибиться (`1.10` против `1.9`), а счётчик сравнивается
однозначно.

Проверять это ОБЯЗАН клиент. Серверная проверка здесь — удобство (поймать
ошибку выпускающего), а не граница безопасности: скомпрометированный
сервер свои же проверки и не выполнит.
"""

from __future__ import annotations

import time
from typing import Optional

from . import signing
from .repository import Repository
from .signing import SignatureError, key_fingerprint

# Реэкспорт общего корня доверия: роутеры и клиенты берут их отсюда,
# не зная про core/signing.
__all__ = ["SignatureError", "key_fingerprint", "canonical_manifest",
           "verify_signature", "publish", "yank", "describe",
           "history", "check", "CHANNELS", "SIGNED_FIELDS",
           "UpdateError"]

CHANNELS = ("stable", "beta")
# Поля, покрываемые подписью. Порядок не важен (ключи сортируются), важен
# СОСТАВ: добавишь поле — старые подписи перестанут сходиться.
SIGNED_FIELDS = ("version", "channel", "platform", "sequence",
                 "size_bytes", "sha256")


# Подпись и её ошибки — общий корень доверия с пакетами узлов
# (core/signing.py): у сервера один способ проверять то, что он
# раздаёт, но не производит.


class UpdateError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


# ---------- Канонический манифест ----------

def canonical_manifest(release: dict) -> bytes:
    """Байты манифеста релиза. Состав полей — часть контракта подписи."""
    return signing.canonical_manifest(
        release, SIGNED_FIELDS, int_fields=("sequence", "size_bytes"))


def verify_signature(release: dict, signature_b64: str,
                     public_key_b64: str) -> None:
    """Проверить подпись манифеста релиза. Бросает SignatureError."""
    signing.verify(canonical_manifest(release), signature_b64, public_key_b64)


# ---------- Публикация ----------

def publish(repo: Repository, *, version: str, channel: str, platform: str,
            sequence: int, url: str, size_bytes: int, sha256: str,
            signature: str, public_key: str, signing_key_id: str = "",
            min_supported: str = "", notes: str = "",
            actor_login: str = "") -> dict:
    """
    Принять выпущенный релиз. Сервер ничего не подписывает — только проверяет
    и сохраняет.

    `sequence` ПРИХОДИТ ОТ ИЗДАТЕЛЯ, а не назначается здесь, и это следствие
    офлайновой подписи: счётчик входит в подписанный манифест, значит на
    момент подписи он уже должен быть известен. Назначь его сервер — подпись
    перестала бы сходиться с тем, что он сохранил.

    Роль сервера — проверить монотонность: счётчик обязан быть больше
    последнего в этом канале. Это не защита клиента (тот проверяет сам,
    сервер ему не доверяет), а защита от ошибки выпускающего — выпустить
    релиз со старым номером значит сделать его невидимым для всех, кто уже
    обновился.
    """
    version = (version or "").strip()
    if not version:
        raise UpdateError("Версия обязательна.")
    if channel not in CHANNELS:
        raise UpdateError(f"channel: {'|'.join(CHANNELS)}, не {channel!r}.")
    if len(sha256 or "") != 64:
        raise UpdateError("sha256 должен быть 64 hex-символа.")
    if not url.strip():
        raise UpdateError("Нужен адрес артефакта.")
    if not public_key.strip():
        raise SignatureError(
            "Публичный ключ выпуска не настроен на сервере — принять релиз "
            "без возможности проверить подпись нельзя.")

    with repo.transaction():
        existing = repo.get_release(version, channel, platform)
        if existing is not None:
            # Перевыпуск той же версии с другим содержимым — это подмена уже
            # раздаваемого артефакта. Хочешь исправить — выпусти новую версию.
            raise UpdateError(
                f"Релиз {version} ({channel}/{platform}) уже опубликован.")

        sequence = int(sequence or 0)
        expected = repo.next_release_sequence(channel, platform)
        if sequence < expected:
            raise UpdateError(
                f"sequence {sequence} не больше уже выпущенных: следующий "
                f"свободный — {expected}. Релиз с меньшим счётчиком не увидит "
                f"никто из обновившихся.")

        release = {"version": version, "channel": channel,
                   "platform": platform, "sequence": sequence,
                   "size_bytes": int(size_bytes or 0), "sha256": sha256}
        verify_signature(release, signature, public_key)

        repo.add_release(
            **release, url=url.strip(), signature=signature,
            signing_key_id=signing_key_id.strip(),
            min_supported=min_supported.strip(), notes=notes.strip(),
            published_by=actor_login or None)
    return describe(repo, version, channel, platform)


def yank(repo: Repository, *, version: str, channel: str, platform: str,
         ) -> dict:
    """
    Отозвать релиз: перестать предлагать его как последний.

    Строка остаётся: история выпусков нужна, чтобы понимать, что стоит у
    пользователя. Отзыв НЕ откатывает уже установленное — для этого выпускают
    новую версию, и это правильный порядок: откат по команде сервера был бы
    ещё одним способом навязать клиенту чужой выбор.
    """
    if not repo.yank_release(version, channel, platform):
        raise UpdateError(
            f"Действующий релиз {version} ({channel}/{platform}) не найден.")
    return describe(repo, version, channel, platform)


def describe(repo: Repository, version: str, channel: str,
             platform: str) -> dict:
    row = repo.get_release(version, channel, platform)
    if row is None:
        raise UpdateError(f"Релиз {version} не найден.")
    return row


def history(repo: Repository, *, channel: Optional[str] = None) -> dict:
    return {"releases": repo.list_releases(channel)}


# ---------- Проверка обновления клиентом ----------

def check(repo: Repository, *, current_version: str = "",
          current_sequence: int = 0, channel: str = "stable",
          platform: str = "any") -> dict:
    """
    Что клиенту делать. Ответ самодостаточен: в нём и манифест, и подпись —
    клиент проверит её сам, своим ключом, до записи файла на диск.

    `mandatory` — версия ниже `min_supported` последнего релиза: сервер лишь
    СООБЩАЕТ об этом, принуждать он не может и не должен. Решение о том, что
    делать с обязательным обновлением, принимает приложение.
    """
    if channel not in CHANNELS:
        raise UpdateError(f"channel: {'|'.join(CHANNELS)}, не {channel!r}.")
    latest = repo.latest_release(channel, platform)
    if latest is None:
        return {"update_available": False, "reason": "no_releases",
                "channel": channel, "platform": platform}

    # Сравниваем по sequence, а не по semver: см. модуль-докстринг.
    if int(current_sequence or 0) >= int(latest["sequence"]):
        return {"update_available": False, "reason": "up_to_date",
                "channel": channel, "platform": platform,
                "latest_version": latest["version"],
                "sequence": latest["sequence"]}

    return {
        "update_available": True,
        "channel": channel,
        "platform": platform,
        # Манифест — ровно те поля, что покрыты подписью, и в том же виде.
        "manifest": {f: latest[f] for f in SIGNED_FIELDS},
        "signature": latest["signature"],
        "signing_key_id": latest["signing_key_id"],
        "url": latest["url"],
        "notes": latest["notes"],
        "published_at": latest["published_at"],
        "mandatory": bool(latest["min_supported"]
                          and current_version
                          and current_version < latest["min_supported"]),
        "checked_at": time.time(),
    }
