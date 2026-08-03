"""
Набор ключей подписи и его ротация.

До этого ключ был один и жил в переменной окружения. Это работает ровно до
первой неприятности: потерял ключ — обновляй всех клиентов вручную, они
носят зашитым старый публичный и другого не примут. Заложить ротацию надо
в ПЕРВУЮ версию клиента; добавить её потом — значит сначала обойти всех
пользователей, ради чего ротация и затевалась.

## Как переносится доверие

Клиент несёт зашитым не ключ, а первый НАБОР. Получив новый набор, он
принимает его, только если тот подписан ключом, активным в наборе, которому
он уже верит. Доверие переходит по цепочке, и смена ключа перестаёт
означать переустановку.

Набор хранится и отдаётся ПОДПИСАННЫМ АРТЕФАКТОМ ЦЕЛИКОМ (`payload` теми же
байтами, что подписывали). Собери сервер payload заново из колонок — любое
расхождение в сериализации сломало бы проверку сразу у всех.

## Чего это НЕ решает

Ротацию при **компрометации**. Укравший приватный ключ подпишет ротацию на
свой — и клиенты примут её, потому что подпись валидна. От этого спасает
только доставка нового набора вне канала: новая сборка, переустановка.
Ротация по цепочке закрывает плановую смену и потерю (когда старый ключ ещё
у вас), и это надо понимать до того, как на неё понадеются.

Смягчение, которое здесь есть: новый ключ обязан **со-подписать** набор.
Это не защищает от кражи старого ключа, но исключает целый класс ошибок —
ротацию на ключ, приватной части которого нет ни у кого (опечатка в base64,
не тот файл), то есть самоблокировку выпуска.

## Откат

`sequence` монотонен. Без него отозванный набор можно подсунуть обратно,
вернув к жизни скомпрометированный ключ, — и подпись будет валидной.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from . import signing
from .repository import Repository
from .signing import SignatureError, key_fingerprint

__all__ = ["SignatureError", "KeyRotationError", "key_fingerprint",
           "canonical_keyset", "verify_keyset", "current_keyset",
           "active_keys", "bootstrap", "rotate", "history"]

KEY_STATUSES = ("active", "revoked")


class KeyRotationError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


# ---------- Канонизация ----------

def canonical_keyset(sequence: int, keys: list) -> str:
    """
    Текст набора — то, что подписывают. Возвращается СТРОКОЙ, а не байтами:
    именно она хранится и отдаётся клиенту, а он проверяет подпись её же
    кодировкой. Разбирать и пересобирать её нельзя.
    """
    payload = {
        "sequence": int(sequence),
        "keys": sorted(
            ({"id": str(k["id"]), "public_key": str(k["public_key"]),
              "status": str(k.get("status", "active"))} for k in keys),
            key=lambda k: k["id"]),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def verify_keyset(payload: str, signature: str, public_key: str) -> None:
    signing.verify(payload.encode("utf-8"), signature, public_key)


def _parse(payload: str) -> dict:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise KeyRotationError(f"Набор ключей не разбирается: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise KeyRotationError("Набор ключей повреждён.")
    return data


# ---------- Чтение ----------

def current_keyset(repo: Repository) -> Optional[dict]:
    """Действующий набор: payload как есть, подпись и разобранный вид."""
    row = repo.latest_key_set()
    if row is None:
        return None
    data = _parse(row["payload"])
    return {"sequence": int(data.get("sequence") or 0),
            "keys": data["keys"], "payload": row["payload"],
            "signature": row["signature"], "signed_by": row["signed_by"],
            "published_at": row["published_at"]}


def active_keys(repo: Repository) -> list[str]:
    """
    Публичные ключи, которыми СЕЙЧАС разрешено подписывать выпуски.

    Их несколько намеренно: ротация не должна обесценивать уже выпущенное.
    Релиз, подписанный вчерашним ключом, остаётся проверяемым, пока этот
    ключ не отозван явно.
    """
    keyset = current_keyset(repo)
    if keyset is None:
        return []
    return [k["public_key"] for k in keyset["keys"]
            if k.get("status") == "active"]


def verify_with_active(repo: Repository, manifest_bytes: bytes,
                       signature: str) -> str:
    """
    Проверить подпись любым активным ключом. Возвращает отпечаток
    подошедшего — его пишут в `signing_key_id`, чтобы потом было видно, чем
    именно подписан выпуск.
    """
    keys = active_keys(repo)
    if not keys:
        raise SignatureError(
            "На сервере не настроен ни один ключ подписи — принять "
            "подписанное содержимое нечем.")
    for key in keys:
        try:
            signing.verify(manifest_bytes, signature, key)
            return key_fingerprint(key)
        except SignatureError:
            continue
    raise SignatureError(
        "Подпись не соответствует ни одному действующему ключу выпуска.")


# ---------- Установка и ротация ----------

def bootstrap(repo: Repository, public_key: str,
              actor_login: str = "") -> dict:
    """
    Завести ПЕРВЫЙ набор из одного ключа.

    Он единственный неподписанный, и это не упущение: подписывать его нечем
    — доверие к нему устанавливается вне канала (ключ кладёт администратор в
    окружение, клиент несёт его в сборке). Дальше каждый следующий набор
    подписан предыдущим.
    """
    public_key = (public_key or "").strip()
    if not public_key:
        raise KeyRotationError("Нужен публичный ключ.")
    if not key_fingerprint(public_key):
        raise KeyRotationError("Публичный ключ не разбирается как base64.")
    with repo.transaction():
        if repo.latest_key_set() is not None:
            raise KeyRotationError(
                "Набор ключей уже заведён — дальше только ротация, иначе "
                "цепочка доверия рвётся.")
        keys = [{"id": key_fingerprint(public_key),
                 "public_key": public_key, "status": "active"}]
        payload = canonical_keyset(1, keys)
        repo.add_key_set(sequence=1, payload=payload, signature="",
                         signed_by="", published_by=actor_login or None)
    return current_keyset(repo)


def rotate(repo: Repository, *, payload: str, signature: str,
           new_key_signature: str = "", actor_login: str = "") -> dict:
    """
    Принять новый набор ключей.

    Проверок три, и каждая закрывает свой класс беды:

    1. **Подпись действующим ключом** — цепочка доверия. Набор, подписанный
       чем-то посторонним, не принимается, иначе ротация была бы способом
       подменить ключ кому угодно.
    2. **Монотонный `sequence`** — откат. Иначе отозванный набор можно
       подсунуть обратно и воскресить скомпрометированный ключ; подпись при
       этом валидна и не помогает.
    3. **Со-подпись новым ключом** (`new_key_signature`) — владение. Не
       защищает от кражи старого ключа, но исключает ротацию на ключ, чьей
       приватной части нет ни у кого: опечатка в base64 или не тот файл
       заблокировали бы выпуск навсегда.
    """
    data = _parse(payload)
    sequence = int(data.get("sequence") or 0)
    keys = data["keys"]
    if not keys:
        raise KeyRotationError("Набор не может быть пустым.")
    for key in keys:
        if key.get("status") not in KEY_STATUSES:
            raise KeyRotationError(
                f"status ключа: {'|'.join(KEY_STATUSES)}, "
                f"не {key.get('status')!r}.")
    if not any(k.get("status") == "active" for k in keys):
        raise KeyRotationError(
            "В наборе не осталось активных ключей — выпускать станет нечем.")

    # Канонизация должна совпасть: иначе подписали одно, а хранить будем
    # другое, и клиент не сойдётся с сервером.
    if canonical_keyset(sequence, keys) != payload:
        raise KeyRotationError(
            "Payload не канонизирован: пересоберите его тем же способом, "
            "которым подписывали (scripts/sign_release.py rotate).")

    with repo.transaction():
        previous = current_keyset(repo)
        if previous is None:
            raise KeyRotationError(
                "Ротировать нечего: сначала заведите первый набор.")
        if sequence <= previous["sequence"]:
            raise KeyRotationError(
                f"sequence {sequence} не больше действующего "
                f"{previous['sequence']}: приняв его, сервер вернул бы к "
                f"жизни отозванный набор.")

        signed_by = verify_with_active(repo, payload.encode("utf-8"), signature)

        # Со-подпись: каждый ключ, которого не было раньше, должен доказать
        # владение приватной частью.
        known = {k["public_key"] for k in previous["keys"]}
        fresh = [k for k in keys
                 if k["public_key"] not in known and k["status"] == "active"]
        if fresh:
            if not new_key_signature:
                raise KeyRotationError(
                    "Новый ключ обязан со-подписать набор: без этого можно "
                    "ротировать на ключ, приватной части которого нет ни у "
                    "кого, и заблокировать выпуск навсегда.")
            for key in fresh:
                try:
                    signing.verify(payload.encode("utf-8"),
                                   new_key_signature, key["public_key"])
                    break
                except SignatureError:
                    continue
            else:
                raise SignatureError(
                    "Со-подпись не соответствует ни одному новому ключу.")

        repo.add_key_set(sequence=sequence, payload=payload,
                         signature=signature, signed_by=signed_by,
                         published_by=actor_login or None)
    return current_keyset(repo)


def history(repo: Repository) -> dict:
    sets = []
    for row in repo.list_key_sets():
        data = _parse(row["payload"])
        sets.append({
            "sequence": int(data.get("sequence") or 0),
            "keys": [{"id": k["id"], "status": k["status"]}
                     for k in data["keys"]],
            "signed_by": row["signed_by"],
            "published_by": row["published_by"],
            "published_at": row["published_at"],
        })
    return {"key_sets": sets}


def ensure_bootstrapped(repo: Repository, env_public_key: str) -> None:
    """
    Завести первый набор из ключа в окружении, если наборов ещё нет.

    Совместимость: до ротации ключ жил только в `RELEASE_PUBLIC_KEY`, и
    сервер обязан продолжать работать с тем же значением, ничего не требуя
    от администратора. Зовётся лениво из роутеров, а не на старте, — чтобы
    сервис без настроенного ключа поднимался как раньше.
    """
    if not (env_public_key or "").strip():
        return
    if repo.latest_key_set() is not None:
        return
    try:
        bootstrap(repo, env_public_key)
    except KeyRotationError:
        pass                    # завели параллельно — не наша забота


def key_set_response(repo: Repository) -> dict:
    """Что отдать клиенту: подписанный набор ровно теми байтами."""
    keyset = current_keyset(repo)
    if keyset is None:
        return {"configured": False}
    return {
        "configured": True,
        "sequence": keyset["sequence"],
        "payload": keyset["payload"],
        "signature": keyset["signature"],
        "signed_by": keyset["signed_by"],
        "fingerprints": [k["id"] for k in keyset["keys"]
                         if k["status"] == "active"],
    }


def touch(repo: Repository) -> float:
    return time.time()
