"""
Пакеты узлов графа: односторонняя докачка с сервера.

Проверяем то, ради чего компромисс и выбран:

  * публиковать может только админ и только подписанное — с десктопов
    наружу ничего не уходит;
  * пакет не может перехватить встроенный тип узла (обязателен префикс) и
    не может объявить тип, уже занятый другим пакетом;
  * `node_types` входит в подписанный манифест — иначе кто угодно заявил бы,
    что его пакет даёт `formula`;
  * граф с узлом из неустановленного пакета отвергается НА PUSH'Е с внятной
    причиной, а не падает потом при генерации;
  * до появления первого пакета механизм не меняет поведение синка.

Запуск: python -m unittest core.test_node_packages -v
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

from core import node_packages, organizations_api, sync_api  # noqa: E402
from core.repository import Repository  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import packages as packages_router  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAS_CRYPTO = True
except ImportError:                                  # pragma: no cover
    HAS_CRYPTO = False

SHA = "c" * 64


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class PackageTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        # Тот же шаг, что делает сервис при старте: развёртыванию нужен
        # администратор развёртывания (is_superuser), иначе пакеты, ключи,
        # выпуски и публичный API закрыты для всех. Роль admin теперь
        # означает «админ своей организации» — см. §8.2.
        organizations_api.ensure_bootstrapped(self.repo)
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.subject = self.repo.ensure_subject(3, "Физика")

        self.key = Ed25519PrivateKey.generate()
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()

    def tearDown(self):
        self.repo.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.unlink(self.db_path + suffix)

    def _manifest(self, **over) -> dict:
        m = {"name": "physics", "version": "1.0.0", "sequence": 1,
             "size_bytes": 2048, "sha256": SHA, "api_version": "1",
             "node_types": ["physics.projectile", "physics.pendulum"]}
        m.update(over)
        return m

    def _sign(self, manifest: dict) -> str:
        return base64.b64encode(self.key.sign(
            node_packages.canonical_manifest(manifest))).decode()

    def _publish(self, **over) -> dict:
        m = self._manifest(**over)
        return node_packages.publish(
            self.repo, url="https://dist.example/physics.zip",
            signature=self._sign(m), public_key=self.pub,
            actor_login="root", **m)


# ---------- Подпись и объявление типов ----------

class SigningTests(PackageTestBase):
    def test_publish_and_catalog(self):
        out = self._publish()
        self.assertEqual(out["name"], "physics")
        cat = node_packages.catalog(self.repo)["packages"]
        self.assertEqual(len(cat), 1)
        self.assertFalse(cat[0]["installed"], "публикация ≠ установка")

    def test_node_types_are_covered_by_the_signature(self):
        """Иначе кто угодно заявил бы, что его пакет даёт formula."""
        m = self._manifest()
        sig = self._sign(m)
        tampered = dict(m, node_types=["physics.projectile", "formula"])
        with self.assertRaises(node_packages.SignatureError):
            node_packages.verify_signature(tampered, sig, self.pub)

    def test_tampered_artifact_is_rejected(self):
        m = self._manifest()
        sig = self._sign(m)
        with self.assertRaises(node_packages.SignatureError):
            node_packages.verify_signature(dict(m, sha256="d" * 64), sig,
                                           self.pub)

    def test_publish_without_key_is_refused(self):
        m = self._manifest()
        with self.assertRaises(node_packages.SignatureError):
            node_packages.publish(self.repo, url="u", signature=self._sign(m),
                                  public_key="", **m)

    def test_node_types_must_be_namespaced(self):
        # Без префикса пакет перехватил бы встроенный узел.
        m = self._manifest(node_types=["formula", "physics.ok"])
        with self.assertRaisesRegex(node_packages.PackageError, "physics"):
            node_packages.publish(self.repo, url="u", signature=self._sign(m),
                                  public_key=self.pub, **m)

    def test_two_packages_cannot_claim_the_same_type(self):
        self._publish()
        m = self._manifest(name="optics", version="1.0.0",
                           node_types=["optics.lens"])
        node_packages.publish(self.repo, url="u", signature=self._sign(m),
                              public_key=self.pub, **m)
        clash = self._manifest(name="optics", version="1.1.0", sequence=2,
                               node_types=["optics.lens",
                                           "physics.projectile"])
        # physics.projectile уже занят — но и префикс не тот, ловится раньше.
        with self.assertRaises(node_packages.PackageError):
            node_packages.publish(self.repo, url="u",
                                  signature=self._sign(clash),
                                  public_key=self.pub, **clash)

    def test_republish_and_rollback_are_refused(self):
        self._publish()
        with self.assertRaisesRegex(node_packages.PackageError, "уже опубликован"):
            self._publish()
        with self.assertRaisesRegex(node_packages.PackageError, "sequence"):
            self._publish(version="0.9.0", sequence=1)

    def test_unsupported_api_version(self):
        m = self._manifest(api_version="99")
        with self.assertRaisesRegex(node_packages.PackageError, "api_version"):
            node_packages.publish(self.repo, url="u", signature=self._sign(m),
                                  public_key=self.pub, **m)


# ---------- Набор сервера ----------

class InstallTests(PackageTestBase):
    def test_install_makes_types_available(self):
        self._publish()
        self.assertEqual(node_packages.installed_node_types(self.repo), set())
        node_packages.install(self.repo, name="physics", actor_login="root")
        self.assertEqual(node_packages.installed_node_types(self.repo),
                         {"physics.projectile", "physics.pendulum"})

    def test_uninstall(self):
        self._publish()
        node_packages.install(self.repo, name="physics")
        node_packages.uninstall(self.repo, name="physics")
        self.assertEqual(node_packages.installed_node_types(self.repo), set())

    def test_cannot_install_yanked(self):
        self._publish()
        node_packages.yank(self.repo, name="physics", version="1.0.0")
        with self.assertRaisesRegex(node_packages.PackageError, "отозван"):
            node_packages.install(self.repo, name="physics", version="1.0.0")

    def test_manifest_for_install_carries_signature(self):
        self._publish()
        out = node_packages.manifest_for_install(self.repo, "physics")
        self.assertEqual(set(out["manifest"]), set(node_packages.SIGNED_FIELDS))
        # Клиент обязан суметь проверить подпись ровно по отданному манифесту.
        node_packages.verify_signature(out["manifest"], out["signature"],
                                       self.pub)


# ---------- Разрешение зависимостей графа ----------

class GraphRequirementTests(PackageTestBase):
    GRAPH = {"nodes": [{"id": "a", "type": "formula", "params": {}},
                       {"id": "b", "type": "physics.projectile", "params": {}}],
             "edges": []}

    def _push_graph(self, params):
        return sync_api.push(
            self.repo, device_id="d", user_id="alla", role="teacher",
            changed_entities=[{"kind": "partition", "id": None,
                               "base_version": 0,
                               "data": {"subject_id": self.subject,
                                        "partition_name": "Граф",
                                        "constracted": 4,
                                        "generation_parametrs": params}}])

    def test_graph_node_types_extracted_from_the_graph_itself(self):
        self.assertEqual(node_packages.graph_node_types(self.GRAPH),
                         {"formula", "physics.projectile"})
        self.assertEqual(node_packages.graph_node_types("не граф"), set())

    def test_push_is_rejected_when_package_missing(self):
        self._publish()
        out = self._push_graph(self.GRAPH)
        self.assertEqual(out["accepted"], [])
        conflict = out["conflicts"][0]
        self.assertEqual(conflict["missing_packages"], ["physics"])
        self.assertIn("physics", conflict["error"])

    def test_rejection_queues_a_request_for_the_admin(self):
        self._publish()
        self._push_graph(self.GRAPH)
        reqs = node_packages.pending_requests(self.repo)["requests"]
        self.assertEqual([(r["name"], r["requested_by"]) for r in reqs],
                         [("physics", "alla")])

    def test_push_succeeds_once_admin_installs(self):
        self._publish()
        self._push_graph(self.GRAPH)
        node_packages.install(self.repo, name="physics", actor_login="root")
        out = self._push_graph(self.GRAPH)
        self.assertEqual(len(out["accepted"]), 1, "теперь принимается")
        # И запрос закрылся сам.
        self.assertEqual(
            node_packages.pending_requests(self.repo)["requests"], [])

    def test_unknown_type_without_any_package_is_named_as_such(self):
        out = self._push_graph({"nodes": [{"id": "x", "type": "нет.такого"}]})
        conflict = out["conflicts"][0]
        self.assertEqual(conflict["missing_packages"], [])
        self.assertEqual(conflict["unknown_node_types"], ["нет.такого"])

    def test_builtin_only_graph_passes(self):
        out = self._push_graph({"nodes": [{"id": "a", "type": "formula"}]})
        self.assertEqual(len(out["accepted"]), 1)

    def test_non_graph_partition_is_untouched(self):
        # До появления пакетов механизм не меняет поведение синка.
        out = self._push_graph({"any": "params"})
        self.assertEqual(len(out["accepted"]), 1)


# ---------- Роутер ----------

class RouterTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        os.environ["RELEASE_PUBLIC_KEY"] = self.pub
        app = FastAPI()
        errors.install(app)
        app.include_router(packages_router.router)
        app.state.repo = self.repo
        self.http = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.environ.pop("RELEASE_PUBLIC_KEY", None)
        super().tearDown()

    @staticmethod
    def _h(login, role):
        return {"X-User-Id": login, "X-User-Role": role}

    def test_publishing_requires_admin(self):
        body = dict(self._manifest(), url="u",
                    signature=self._sign(self._manifest()))
        self.assertEqual(
            self.http.post("/admin/packages", json=body).status_code, 401)
        self.assertEqual(
            self.http.post("/admin/packages", json=body,
                           headers=self._h("alla", "teacher")).status_code, 403)

    def test_catalog_is_open(self):
        # Пакет нужен, чтобы граф открылся; запирать это за токеном значит
        # ломать работу тому, у кого он протух.
        self.assertEqual(self.http.get("/packages").status_code, 200)

    def test_full_flow(self):
        h = self._h("root", "admin")
        m = self._manifest()
        body = dict(m, url="https://dist.example/p.zip", signature=self._sign(m))
        self.assertEqual(
            self.http.post("/admin/packages", json=body, headers=h).status_code,
            200)

        cat = self.http.get("/packages").json()["packages"]
        self.assertFalse(cat[0]["installed"])

        self.assertEqual(
            self.http.post("/admin/packages/physics/install", json={},
                           headers=h).status_code, 200)
        cat = self.http.get("/packages").json()["packages"]
        self.assertTrue(cat[0]["installed"])
        self.assertEqual(cat[0]["installed_version"], "1.0.0")

        man = self.http.get("/packages/physics/manifest").json()
        node_packages.verify_signature(man["manifest"], man["signature"],
                                       self.pub)

        self.assertEqual(
            self.http.delete("/admin/packages/physics/install",
                             headers=h).status_code, 200)

    def test_tampered_publish_is_400(self):
        m = self._manifest()
        body = dict(m, url="u", signature=self._sign(m), sha256="e" * 64)
        r = self.http.post("/admin/packages", json=body,
                           headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 400)

    def test_requests_queue_is_admin_only(self):
        self.assertEqual(
            self.http.get("/admin/packages/requests").status_code, 401)
        self.assertEqual(
            self.http.get("/admin/packages/requests",
                          headers=self._h("root", "admin")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
