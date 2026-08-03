"""
Ротация ключа выпуска.

До неё ключ был один и жил в переменной окружения: потерял — обходи всех
пользователей вручную. Здесь проверяется, что доверие переносится по
цепочке и что цепочку нельзя подделать:

  * новый набор принимается, только если подписан ключом, активным в
    ДЕЙСТВУЮЩЕМ наборе;
  * `sequence` монотонен — иначе отозванный набор подсовывают обратно и
    воскрешают скомпрометированный ключ, а подпись при этом валидна;
  * новый ключ обязан со-подписать набор: это не защита от кражи, а защита
    от ротации на ключ, приватной части которого нет ни у кого;
  * ротация НЕ обесценивает уже выпущенное — релиз, подписанный вчерашним
    ключом, проверяется, пока тот не отозван явно;
  * отзыв ключа действительно перестаёт принимать его подписи;
  * набор без активных ключей не принимается — выпускать станет нечем.

Запуск: python -m unittest core.test_signing_keys -v
"""

from __future__ import annotations
import base64
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core import signing_keys, updates  # noqa: E402
from core.repository import Repository  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAS_CRYPTO = True
except ImportError:                                  # pragma: no cover
    HAS_CRYPTO = False


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class KeyRotationTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.k1, self.pub1 = self._keypair()
        self.k2, self.pub2 = self._keypair()
        signing_keys.bootstrap(self.repo, self.pub1, actor_login="root")

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    @staticmethod
    def _keypair():
        key = Ed25519PrivateKey.generate()
        pub = base64.b64encode(key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()
        return key, pub

    def _keyset(self, sequence: int, keys: list) -> str:
        return signing_keys.canonical_keyset(sequence, keys)

    def _sign(self, key, payload: str) -> str:
        return base64.b64encode(key.sign(payload.encode("utf-8"))).decode()

    def _entry(self, pub: str, status: str = "active") -> dict:
        return {"id": signing_keys.key_fingerprint(pub),
                "public_key": pub, "status": status}

    def _rotate_to_k2(self, sequence: int = 2, revoke_old: bool = False):
        keys = [self._entry(self.pub2),
                self._entry(self.pub1, "revoked" if revoke_old else "active")]
        payload = self._keyset(sequence, keys)
        return signing_keys.rotate(
            self.repo, payload=payload, signature=self._sign(self.k1, payload),
            new_key_signature=self._sign(self.k2, payload), actor_login="root")

    def _publish(self, key, version: str, sequence: int):
        release = {"version": version, "channel": "stable", "platform": "any",
                   "sequence": sequence, "size_bytes": 10, "sha256": "a" * 64}
        return updates.publish(
            self.repo, url="https://d/a.zip", public_key="",
            signature=base64.b64encode(
                key.sign(updates.canonical_manifest(release))).decode(),
            **release)


class BootstrapTests(KeyRotationTestBase):
    def test_first_set_is_unsigned_and_that_is_deliberate(self):
        # Подписывать его нечем: доверие к нему ставится вне канала.
        keyset = signing_keys.current_keyset(self.repo)
        self.assertEqual(keyset["sequence"], 1)
        self.assertEqual(keyset["signature"], "")
        self.assertEqual(signing_keys.active_keys(self.repo), [self.pub1])

    def test_cannot_bootstrap_twice(self):
        with self.assertRaisesRegex(signing_keys.KeyRotationError, "уже заведён"):
            signing_keys.bootstrap(self.repo, self.pub2)

    def test_garbage_key_refused(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        repo = Repository(path)
        try:
            with self.assertRaises(signing_keys.KeyRotationError):
                signing_keys.bootstrap(repo, "не-base64!!!")
        finally:
            repo.close()
            for s in ("", "-wal", "-shm"):
                if os.path.exists(path + s):
                    os.unlink(path + s)


class RotationTests(KeyRotationTestBase):
    def test_chain_of_trust(self):
        out = self._rotate_to_k2()
        self.assertEqual(out["sequence"], 2)
        self.assertIn(self.pub2, signing_keys.active_keys(self.repo))
        # Клиент, несущий ПЕРВЫЙ ключ, обязан суметь проверить новый набор.
        signing_keys.verify_keyset(out["payload"], out["signature"], self.pub1)

    def test_set_signed_by_outsider_is_refused(self):
        stranger, _ = self._keypair()
        payload = self._keyset(2, [self._entry(self.pub2)])
        with self.assertRaises(signing_keys.SignatureError):
            signing_keys.rotate(
                self.repo, payload=payload,
                signature=self._sign(stranger, payload),
                new_key_signature=self._sign(self.k2, payload))

    def test_rollback_of_the_set_is_refused(self):
        self._rotate_to_k2(sequence=2)
        keys = [self._entry(self.pub1)]
        payload = self._keyset(2, keys)
        with self.assertRaisesRegex(signing_keys.KeyRotationError, "sequence"):
            signing_keys.rotate(self.repo, payload=payload,
                                signature=self._sign(self.k1, payload))

    def test_new_key_must_prove_possession(self):
        # Иначе можно ротировать на ключ, приватной части которого нет ни у
        # кого, и заблокировать выпуск навсегда.
        payload = self._keyset(2, [self._entry(self.pub2),
                                   self._entry(self.pub1)])
        with self.assertRaisesRegex(signing_keys.KeyRotationError, "со-подпис"):
            signing_keys.rotate(self.repo, payload=payload,
                                signature=self._sign(self.k1, payload))

    def test_wrong_co_signature_is_refused(self):
        stranger, _ = self._keypair()
        payload = self._keyset(2, [self._entry(self.pub2),
                                   self._entry(self.pub1)])
        with self.assertRaises(signing_keys.SignatureError):
            signing_keys.rotate(
                self.repo, payload=payload,
                signature=self._sign(self.k1, payload),
                new_key_signature=self._sign(stranger, payload))

    def test_set_without_active_keys_is_refused(self):
        payload = self._keyset(2, [self._entry(self.pub1, "revoked")])
        with self.assertRaisesRegex(signing_keys.KeyRotationError, "активных"):
            signing_keys.rotate(self.repo, payload=payload,
                                signature=self._sign(self.k1, payload))

    def test_non_canonical_payload_is_refused(self):
        # Подписали одно, хранили бы другое — клиент не сошёлся бы с сервером.
        keys = [self._entry(self.pub2), self._entry(self.pub1)]
        payload = json.dumps({"sequence": 2, "keys": keys})   # без канонизации
        with self.assertRaisesRegex(signing_keys.KeyRotationError,
                                    "канонизирован"):
            signing_keys.rotate(
                self.repo, payload=payload,
                signature=self._sign(self.k1, payload),
                new_key_signature=self._sign(self.k2, payload))

    def test_history_records_who_signed_what(self):
        self._rotate_to_k2()
        sets = signing_keys.history(self.repo)["key_sets"]
        self.assertEqual([s["sequence"] for s in sets], [2, 1])
        self.assertEqual(sets[0]["signed_by"],
                         signing_keys.key_fingerprint(self.pub1))


class RotationDoesNotBreakReleasesTests(KeyRotationTestBase):
    def test_old_key_still_verifies_until_revoked(self):
        self._publish(self.k1, "1.0.0", 1)
        self._rotate_to_k2()
        # Ротация не обесценивает уже выпущенное и не мешает выпускать старым.
        self._publish(self.k1, "1.1.0", 2)
        self._publish(self.k2, "1.2.0", 3)

    def test_revoked_key_stops_being_accepted(self):
        self._rotate_to_k2(revoke_old=True)
        self.assertEqual(signing_keys.active_keys(self.repo), [self.pub2])
        self._publish(self.k2, "2.0.0", 1)
        with self.assertRaises(signing_keys.SignatureError):
            self._publish(self.k1, "2.1.0", 2)

    def test_signing_key_id_records_which_key_matched(self):
        self._rotate_to_k2()
        out = self._publish(self.k2, "1.1.0", 2)
        self.assertEqual(out["signing_key_id"],
                         signing_keys.key_fingerprint(self.pub2))

    def test_publish_without_any_key_set_is_refused(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        repo = Repository(path)
        try:
            release = {"version": "1.0.0", "channel": "stable",
                       "platform": "any", "sequence": 1, "size_bytes": 10,
                       "sha256": "a" * 64}
            with self.assertRaisesRegex(signing_keys.SignatureError,
                                        "не настроен"):
                updates.publish(repo, url="u", public_key="", signature="x",
                                **release)
        finally:
            repo.close()
            for s in ("", "-wal", "-shm"):
                if os.path.exists(path + s):
                    os.unlink(path + s)


class BootstrapFromEnvTests(KeyRotationTestBase):
    def test_legacy_env_key_seeds_the_first_set(self):
        # Совместимость: до ротации ключ жил только в RELEASE_PUBLIC_KEY, и
        # сервер обязан продолжать работать с тем же значением.
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)
        repo = Repository(path)
        try:
            self.assertIsNone(signing_keys.current_keyset(repo))
            signing_keys.ensure_bootstrapped(repo, self.pub1)
            self.assertEqual(signing_keys.active_keys(repo), [self.pub1])
            # Повторный вызов ничего не ломает.
            signing_keys.ensure_bootstrapped(repo, self.pub2)
            self.assertEqual(signing_keys.active_keys(repo), [self.pub1])
        finally:
            repo.close()
            for s in ("", "-wal", "-shm"):
                if os.path.exists(path + s):
                    os.unlink(path + s)


if __name__ == "__main__":
    unittest.main()
