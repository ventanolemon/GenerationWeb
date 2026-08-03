"""
Обновление десктопа: подписанные релизы.

Это канал доставки исполняемого кода на машины пользователей, поэтому
тесты проверяют не «работает ли», а **что именно он не даёт сделать**:

  * подменить артефакт при валидной подписи (хеш входит в подписанное);
  * переклеить честно подписанный артефакт под другую версию, платформу
    или канал — подпись покрывает манифест целиком, а не только хеш;
  * подсунуть старый подписанный релиз (защита от отката по sequence);
  * принять релиз, когда проверить подпись нечем.

Плюс то, что подпись НЕ должна ломать: отозванный релиз перестаёт
предлагаться, но остаётся в истории.

Запуск: python -m unittest core.test_updates -v
"""

from __future__ import annotations
import base64
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import updates  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import updates as updates_router  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAS_CRYPTO = True
except ImportError:                                  # pragma: no cover
    HAS_CRYPTO = False

SHA = "a" * 64


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class UpdatesTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")

        self.key = Ed25519PrivateKey.generate()
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    def _sign(self, **over) -> tuple[dict, str]:
        release = {"version": "1.0.0", "channel": "stable", "platform": "any",
                   "sequence": 1, "size_bytes": 1024, "sha256": SHA}
        release.update(over)
        sig = base64.b64encode(
            self.key.sign(updates.canonical_manifest(release))).decode()
        return release, sig

    def _publish(self, **over):
        release, sig = self._sign(**over)
        return updates.publish(
            self.repo, url="https://dist.example/app.zip", signature=sig,
            public_key=self.pub, actor_login="root",
            **{k: v for k, v in release.items()})


# ---------- Канонический манифест ----------

class ManifestTests(UpdatesTestBase):
    def test_manifest_is_byte_stable(self):
        # Подписывающая и проверяющая стороны обязаны получать одно и то же.
        a = updates.canonical_manifest(
            {"version": "1.0.0", "channel": "stable", "platform": "any",
             "sequence": 1, "size_bytes": 10, "sha256": SHA})
        b = updates.canonical_manifest(
            {"sha256": SHA, "size_bytes": "10", "sequence": "1",
             "platform": "any", "channel": "stable", "version": "1.0.0"})
        self.assertEqual(a, b, "порядок ключей и типы не влияют")

    def test_manifest_covers_more_than_the_hash(self):
        base = {"version": "1.0.0", "channel": "stable", "platform": "any",
                "sequence": 1, "size_bytes": 10, "sha256": SHA}
        for field, other in (("version", "9.9.9"), ("platform", "win"),
                             ("channel", "beta"), ("sequence", 42),
                             ("size_bytes", 11)):
            with self.subTest(field=field):
                self.assertNotEqual(updates.canonical_manifest(base),
                                    updates.canonical_manifest(
                                        dict(base, **{field: other})))


# ---------- Подпись ----------

class SignatureTests(UpdatesTestBase):
    def test_valid_signature_passes(self):
        release, sig = self._sign()
        updates.verify_signature(release, sig, self.pub)

    def test_swapped_artifact_is_rejected(self):
        release, sig = self._sign()
        release["sha256"] = "b" * 64
        with self.assertRaises(updates.SignatureError):
            updates.verify_signature(release, sig, self.pub)

    def test_relabelled_release_is_rejected(self):
        """Переклеить подписанный артефакт под другую версию нельзя."""
        release, sig = self._sign(version="1.0.0")
        for field, other in (("version", "2.0.0"), ("platform", "win"),
                             ("channel", "beta"), ("sequence", 99)):
            with self.subTest(field=field):
                with self.assertRaises(updates.SignatureError):
                    updates.verify_signature(dict(release, **{field: other}),
                                             sig, self.pub)

    def test_foreign_key_is_rejected(self):
        release, sig = self._sign()
        other = base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw)).decode()
        with self.assertRaises(updates.SignatureError):
            updates.verify_signature(release, sig, other)

    def test_garbage_signature_is_an_error_not_a_crash(self):
        release, _ = self._sign()
        for bad in ("не base64", "", "AAAA"):
            with self.assertRaises(updates.SignatureError):
                updates.verify_signature(release, bad, self.pub)


# ---------- Публикация ----------

class PublishTests(UpdatesTestBase):
    def test_publish_and_fetch(self):
        out = self._publish()
        self.assertEqual(out["version"], "1.0.0")
        self.assertEqual(out["sequence"], 1)
        self.assertEqual(out["published_by"], "root")

    def test_publish_without_public_key_is_refused(self):
        release, sig = self._sign()
        with self.assertRaisesRegex(updates.SignatureError, "не настроен"):
            updates.publish(self.repo, url="u", signature=sig, public_key="",
                            **release)

    def test_publish_with_bad_signature_is_refused(self):
        release, _ = self._sign()
        other_sig = base64.b64encode(
            Ed25519PrivateKey.generate().sign(b"nonsense")).decode()
        with self.assertRaises(updates.SignatureError):
            updates.publish(self.repo, url="u", signature=other_sig,
                            public_key=self.pub, **release)
        self.assertEqual(updates.history(self.repo)["releases"], [],
                         "непринятый релиз не сохраняется")

    def test_republishing_same_version_is_refused(self):
        # Перевыпуск той же версии другим содержимым — подмена раздаваемого.
        self._publish()
        with self.assertRaisesRegex(updates.UpdateError, "уже опубликован"):
            self._publish()

    def test_bad_metadata_is_refused(self):
        for over, pattern in (({"sha256": "короткий"}, "sha256"),
                              ({"channel": "внезапно"}, "channel")):
            with self.subTest(over=over):
                release, sig = self._sign(**over)
                with self.assertRaises(updates.UpdateError):
                    updates.publish(self.repo, url="u", signature=sig,
                                    public_key=self.pub, **release)


# ---------- Проверка обновления ----------

class CheckTests(UpdatesTestBase):
    def test_no_releases(self):
        out = updates.check(self.repo)
        self.assertFalse(out["update_available"])
        self.assertEqual(out["reason"], "no_releases")

    def test_update_offered_with_manifest_and_signature(self):
        self._publish()
        out = updates.check(self.repo, current_sequence=0)
        self.assertTrue(out["update_available"])
        self.assertEqual(set(out["manifest"]), set(updates.SIGNED_FIELDS))
        # Клиент обязан суметь проверить подпись ровно по отданному манифесту.
        updates.verify_signature(out["manifest"], out["signature"], self.pub)

    def test_current_client_is_told_it_is_up_to_date(self):
        self._publish()
        out = updates.check(self.repo, current_sequence=1)
        self.assertFalse(out["update_available"])
        self.assertEqual(out["reason"], "up_to_date")

    def test_rollback_is_not_offered(self):
        """Клиент с более свежим sequence обновление не получает."""
        self._publish(version="1.0.0", sequence=1)
        self._publish(version="1.1.0", sequence=2)
        self.assertFalse(
            updates.check(self.repo, current_sequence=2)["update_available"])
        self.assertFalse(
            updates.check(self.repo, current_sequence=5)["update_available"])

    def test_latest_wins_by_sequence(self):
        self._publish(version="1.0.0", sequence=1)
        self._publish(version="1.1.0", sequence=2)
        out = updates.check(self.repo, current_sequence=1)
        self.assertEqual(out["manifest"]["version"], "1.1.0")

    def test_yanked_release_is_not_offered_but_stays_in_history(self):
        self._publish(version="1.0.0", sequence=1)
        self._publish(version="1.1.0", sequence=2)
        updates.yank(self.repo, version="1.1.0", channel="stable",
                     platform="any")
        out = updates.check(self.repo, current_sequence=0)
        self.assertEqual(out["manifest"]["version"], "1.0.0")
        self.assertEqual(len(updates.history(self.repo)["releases"]), 2)

    def test_channels_are_independent(self):
        self._publish(version="1.0.0", channel="stable", sequence=1)
        self._publish(version="2.0.0-beta", channel="beta", sequence=1)
        self.assertEqual(
            updates.check(self.repo, channel="stable")["manifest"]["version"],
            "1.0.0")
        self.assertEqual(
            updates.check(self.repo, channel="beta")["manifest"]["version"],
            "2.0.0-beta")

    def test_mandatory_flag(self):
        self._publish(version="2.0.0", sequence=1)
        # min_supported задаётся при публикации; проверяем оба исхода.
        self.repo.yank_release("2.0.0", "stable", "any")
        release, sig = self._sign(version="2.1.0", sequence=2)
        updates.publish(self.repo, url="u", signature=sig,
                        public_key=self.pub, min_supported="2.0.0", **release)
        self.assertTrue(updates.check(self.repo, current_version="1.5.0",
                                      current_sequence=0)["mandatory"])
        self.assertFalse(updates.check(self.repo, current_version="2.0.5",
                                       current_sequence=0)["mandatory"])


# ---------- Роутер ----------

class RouterTests(UpdatesTestBase):
    def setUp(self):
        super().setUp()
        os.environ["RELEASE_PUBLIC_KEY"] = self.pub
        app = FastAPI()
        errors.install(app)
        app.include_router(updates_router.router)
        app.state.repo = self.repo
        self.http = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.environ.pop("RELEASE_PUBLIC_KEY", None)
        super().tearDown()

    @staticmethod
    def _h(login, role):
        return {"X-User-Id": login, "X-User-Role": role}

    def _body(self, **over):
        release, sig = self._sign(**over)
        return dict(release, signature=sig, url="https://dist.example/a.zip")

    def test_check_needs_no_identity(self):
        # Обновление безопасности должно доезжать и до того, у кого протух
        # токен: подлинность даёт подпись, а не закрытость эндпоинта.
        self.assertEqual(self.http.get("/updates/check").status_code, 200)

    def test_publish_requires_admin(self):
        self.assertEqual(
            self.http.post("/admin/releases", json=self._body()).status_code,
            401)
        self.assertEqual(
            self.http.post("/admin/releases", json=self._body(),
                           headers=self._h("alla", "teacher")).status_code, 403)

    def test_publish_check_yank_flow(self):
        h = self._h("root", "admin")
        self.assertEqual(
            self.http.post("/admin/releases", json=self._body(),
                           headers=h).status_code, 200)

        out = self.http.get("/updates/check?current_sequence=0").json()
        self.assertTrue(out["update_available"])
        updates.verify_signature(out["manifest"], out["signature"], self.pub)

        self.assertEqual(
            self.http.post("/admin/releases/1.0.0/yank", headers=h).status_code,
            200)
        self.assertFalse(
            self.http.get("/updates/check?current_sequence=0").json()
            ["update_available"])

    def test_tampered_publish_is_400(self):
        body = self._body()
        body["sha256"] = "b" * 64          # артефакт подменён после подписи
        r = self.http.post("/admin/releases", json=body,
                           headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Подпись", r.json()["error"]["message"])

    def test_key_endpoint_gives_fingerprints_not_the_key(self):
        # Отпечатков МНОЖЕСТВО: после ротации активных ключей может быть
        # несколько сразу, чтобы уже выпущенное не обесценивалось.
        out = self.http.get("/updates/key").json()
        self.assertTrue(out["configured"])
        self.assertEqual(out["fingerprints"], [updates.key_fingerprint(self.pub)])
        self.assertNotIn(self.pub, str(out), "сам ключ отсюда не раздаётся")

    def test_key_set_is_served_signed_for_the_client(self):
        out = self.http.get("/updates/keys").json()
        self.assertTrue(out["configured"])
        self.assertEqual(out["sequence"], 1)
        # Первый набор неподписан намеренно: доверие к нему ставится вне
        # канала. Дальше каждый следующий подписан предыдущим.
        self.assertEqual(out["signature"], "")
        self.assertIn(self.pub, out["payload"])


if __name__ == "__main__":
    unittest.main()
