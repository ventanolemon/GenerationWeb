"""
Офлайновая подпись релиза десктопа.

    # один раз: завести ключ выпуска
    python -m scripts.sign_release keygen --out release-key

    # на каждый выпуск
    python -m scripts.sign_release sign dist/Generator-1.4.0.zip \
        --version 1.4.0 --sequence 7 --key release-key.priv

Запускается НА МАШИНЕ ВЫПУСКАЮЩЕГО, не на сервере. В этом весь смысл: если
приватный ключ окажется на раздающей машине, взлом сервера превратится в
возможность подписать что угодно и разослать это на все десктопы. Сервер
подпись только проверяет и хранит.

Файл `*.priv` не должен попасть ни в git, ни в образ, ни в бэкап сервера.
Потеря ключа означает выпуск нового и обновление всех клиентов вручную —
поэтому его стоит держать там же, где держат ключи подписи установщиков.

Вывод команды `sign` — готовое тело запроса `POST /admin/releases`.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _load_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey, Ed25519PublicKey)
        from cryptography.hazmat.primitives import serialization
        return Ed25519PrivateKey, Ed25519PublicKey, serialization
    except ImportError:
        sys.exit("Нужна библиотека cryptography: pip install cryptography")


def keygen(args) -> int:
    Ed25519PrivateKey, _, serialization = _load_crypto()
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)

    priv_path = pathlib.Path(f"{args.out}.priv")
    priv_path.write_text(base64.b64encode(priv).decode() + "\n")
    priv_path.chmod(0o600)
    pub_b64 = base64.b64encode(pub).decode()
    pathlib.Path(f"{args.out}.pub").write_text(pub_b64 + "\n")

    from core.updates import key_fingerprint
    print(f"Приватный ключ: {priv_path}  ← НИКОГДА не класть на сервер")
    print(f"Публичный ключ: {args.out}.pub")
    print(f"\nСерверу:   export RELEASE_PUBLIC_KEY={pub_b64}")
    print(f"Отпечаток: {key_fingerprint(pub_b64)}")
    print("\nТот же публичный ключ надо зашить в клиент: клиент, берущий ключ "
          "с того же сервера, что и обновление, не проверяет ничего.")
    return 0


def sign(args) -> int:
    Ed25519PrivateKey, _, _ = _load_crypto()
    from core.updates import canonical_manifest, key_fingerprint

    artifact = pathlib.Path(args.artifact)
    if not artifact.exists():
        sys.exit(f"Нет файла {artifact}")
    data = artifact.read_bytes()

    release = {
        "version": args.version,
        "channel": args.channel,
        "platform": args.platform,
        "sequence": int(args.sequence),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    raw_key = base64.b64decode(pathlib.Path(args.key).read_text().strip())
    key = Ed25519PrivateKey.from_private_bytes(raw_key)
    signature = base64.b64encode(
        key.sign(canonical_manifest(release))).decode()

    from cryptography.hazmat.primitives import serialization
    pub_b64 = base64.b64encode(key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()

    body = dict(release, signature=signature, url=args.url or "",
                signing_key_id=key_fingerprint(pub_b64),
                min_supported=args.min_supported, notes=args.notes)
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if not args.url:
        print("\n# url пуст — подставьте адрес артефакта перед публикацией",
              file=sys.stderr)
    return 0


def rotate(args) -> int:
    """
    Подготовить новый НАБОР ключей: подписать его действующим ключом и
    со-подписать новым.

    Со-подпись обязательна не ради безопасности (украденный старый ключ
    подпишет что угодно), а ради защиты от самоблокировки: она доказывает,
    что приватная часть нового ключа существует и у вас. Опечатка в base64
    или не тот файл иначе заблокировали бы выпуск навсегда.
    """
    Ed25519PrivateKey, _, serialization = _load_crypto()
    from core.signing_keys import canonical_keyset
    from core.updates import key_fingerprint

    def _load(path):
        raw = base64.b64decode(pathlib.Path(path).read_text().strip())
        key = Ed25519PrivateKey.from_private_bytes(raw)
        pub = base64.b64encode(key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()
        return key, pub

    current_key, current_pub = _load(args.current_key)
    new_key, new_pub = _load(args.new_key)

    keys = [{"id": key_fingerprint(new_pub), "public_key": new_pub,
             "status": "active"}]
    if not args.revoke_current:
        # По умолчанию старый ключ остаётся активным: иначе всё уже
        # выпущенное им перестанет проверяться разом.
        keys.append({"id": key_fingerprint(current_pub),
                     "public_key": current_pub, "status": "active"})
    else:
        keys.append({"id": key_fingerprint(current_pub),
                     "public_key": current_pub, "status": "revoked"})

    payload = canonical_keyset(int(args.sequence), keys)
    body = {
        "payload": payload,
        "signature": base64.b64encode(
            current_key.sign(payload.encode("utf-8"))).decode(),
        "new_key_signature": base64.b64encode(
            new_key.sign(payload.encode("utf-8"))).decode(),
    }
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print(f"\n# новый ключ:   {key_fingerprint(new_pub)}", file=sys.stderr)
    print(f"# прежний ключ: {key_fingerprint(current_pub)}"
          f"{' (ОТЗЫВАЕТСЯ)' if args.revoke_current else ' (остаётся активным)'}",
          file=sys.stderr)
    if args.revoke_current:
        print("# ВНИМАНИЕ: всё, подписанное прежним ключом, перестанет "
              "проверяться.", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("keygen", help="завести ключ выпуска")
    g.add_argument("--out", default="release-key")
    g.set_defaults(func=keygen)

    s = sub.add_parser("sign", help="подписать артефакт")
    s.add_argument("artifact")
    s.add_argument("--version", required=True)
    s.add_argument("--sequence", required=True, type=int,
                   help="монотонный счётчик выпуска: защита от отката")
    s.add_argument("--key", required=True, help="файл *.priv")
    s.add_argument("--channel", default="stable")
    s.add_argument("--platform", default="any")
    s.add_argument("--url", default="")
    s.add_argument("--min-supported", dest="min_supported", default="")
    s.add_argument("--notes", default="")
    s.set_defaults(func=sign)

    r = sub.add_parser("rotate", help="сменить набор ключей")
    r.add_argument("--current-key", required=True, help="действующий *.priv")
    r.add_argument("--new-key", required=True, help="новый *.priv")
    r.add_argument("--sequence", required=True, type=int,
                   help="больше действующего: защита от отката набора")
    r.add_argument("--revoke-current", action="store_true",
                   help="отозвать прежний ключ (ломает проверку всего, что "
                        "им подписано)")
    r.set_defaults(func=rotate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
