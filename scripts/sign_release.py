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

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
