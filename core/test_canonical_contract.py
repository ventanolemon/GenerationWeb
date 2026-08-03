"""
Контракт канонизации между сервером и десктопом.

Подпись покрывает БАЙТЫ канонического манифеста. Подписывает их выпускающий
(`scripts/sign_release.py`), проверяет сервер (`core/signing.py`) и —
главное — проверяет клиент, у которого своя реализация в другом репозитории
(Generator, `core/updates/trust.py`). Три места, и все обязаны получать
байт в байт одно и то же.

Круговых прогонов «подписали — проверили» для этого НЕ ДОСТАТОЧНО: они
сходятся и тогда, когда стороны разошлись между собой. Каждая согласна сама
с собой, ни одна не согласна с другой, а выглядит это не как «поменяли
формат», а как «сервер подсовывает подделку», после чего сутки уходят на
поиск лишнего пробела.

Поэтому здесь зафиксированы ТОЧНЫЕ БАЙТЫ. Те же значения продублированы в
Generator (`tests/test_updates_trust.py::CanonicalGoldenTests`): изменение
с любой стороны роняет тесты с обеих, и разойтись молча нельзя.

Менять эти байты можно ровно в одном случае — если сознательно ломается
совместимость со всем, что уже подписано, и обе половины меняются одним
согласованным выпуском.

Запуск: python -m unittest core.test_canonical_contract -v
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core import node_packages, updates                    # noqa: E402
from core.signing_keys import canonical_keyset             # noqa: E402


class CanonicalGoldenTests(unittest.TestCase):
    def test_release_manifest(self):
        self.assertEqual(
            updates.canonical_manifest({
                "version": "1.4.0", "channel": "stable", "platform": "any",
                "sequence": 7, "size_bytes": 1024, "sha256": "ab" * 32}),
            b'{"channel":"stable","platform":"any","sequence":7,'
            b'"sha256":"' + b"ab" * 32 + b'","size_bytes":1024,'
            b'"version":"1.4.0"}')

    def test_package_manifest_sorts_node_types(self):
        # Порядок списка не должен влиять: подписывающий берёт его из
        # argparse, сервер — из JSON-тела, клиент — из ответа API.
        first = node_packages.canonical_manifest({
            "name": "physics", "version": "0.2.0", "sequence": 3,
            "size_bytes": 2048, "sha256": "cd" * 32, "api_version": "1",
            "node_types": ["physics.projectile", "physics.energy"]})
        second = node_packages.canonical_manifest({
            "name": "physics", "version": "0.2.0", "sequence": 3,
            "size_bytes": 2048, "sha256": "cd" * 32, "api_version": "1",
            "node_types": ["physics.energy", "physics.projectile"]})
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            b'{"api_version":"1","name":"physics",'
            b'"node_types":"physics.energy,physics.projectile","sequence":3,'
            b'"sha256":"' + b"cd" * 32 + b'","size_bytes":2048,'
            b'"version":"0.2.0"}')

    def test_keyset(self):
        self.assertEqual(
            canonical_keyset(2, [{"id": "bbb", "public_key": "K2",
                                  "status": "active"},
                                 {"id": "aaa", "public_key": "K1",
                                  "status": "revoked"}]),
            '{"keys":[{"id":"aaa","public_key":"K1","status":"revoked"},'
            '{"id":"bbb","public_key":"K2","status":"active"}],"sequence":2}')

    def test_int_and_str_forms_agree(self):
        # Сервер отдаёт числа, argparse — строки. `1` и `"1"` обязаны давать
        # одинаковые байты, иначе подпись «то сходится, то нет».
        as_int = updates.canonical_manifest({
            "version": "1", "channel": "stable", "platform": "any",
            "sequence": 7, "size_bytes": 1024, "sha256": "x"})
        as_str = updates.canonical_manifest({
            "version": "1", "channel": "stable", "platform": "any",
            "sequence": "7", "size_bytes": "1024", "sha256": "x"})
        self.assertEqual(as_int, as_str)

    def test_signed_field_sets_are_part_of_the_contract(self):
        # Состав подписанного — тоже контракт: добавишь поле, и все ранее
        # выпущенные подписи перестанут сходиться, причём у клиента, который
        # об изменении не знает.
        self.assertEqual(updates.SIGNED_FIELDS,
                         ("version", "channel", "platform", "sequence",
                          "size_bytes", "sha256"))
        self.assertEqual(node_packages.SIGNED_FIELDS,
                         ("name", "version", "sequence", "size_bytes",
                          "sha256", "api_version", "node_types"))


if __name__ == "__main__":
    unittest.main()
