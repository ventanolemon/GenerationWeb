"""
Тесты offline-sync (offline_sync_protocol.md) — headless, свежая SQLite на
каждый тест, без FastAPI (роутер — тонкая обёртка, логика вся в sync_api).

Сценарии верификации из брифа:
  * два «устройства» правят одну партицию офлайн → корректный конфликт с
    ОБЕИМИ версиями, не тихая перезапись;
  * tombstone доезжает до второго устройства как удаление;
  * двойная отправка одной attempt не дублируется;
  * курсорная пагинация не теряет и не дублирует записи между страницами.

Запуск: python -m unittest core.test_sync_protocol -v  (из корня монорепо)
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core import sync_api  # noqa: E402
from core.repository import Repository  # noqa: E402


def _pull_all(repo, device_id, cursors=None, limit=200, user_id=None):
    """pull до пустоты (клиентский цикл §4), вернуть агрегат."""
    cursors = dict(cursors or {})
    agg = {"subjects": [], "partitions": [], "deleted": []}
    while True:
        out = sync_api.pull(repo, device_id=device_id, user_id=user_id,
                            cursors=cursors, limit=limit)
        for k in agg:
            agg[k].extend(out[k])
        cursors = out["new_cursors"]
        if not out["has_more"]:
            return agg, cursors


class SyncTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)          # Repository создаст заново
        self.repo = Repository(self.db_path)
        self.subject_id = self.repo.ensure_subject(3, "Физика")

    def tearDown(self):
        os.unlink(self.db_path)

    def _partition(self, name="Сила F=ma", params=None):
        return self.repo.upsert_partition(
            self.subject_id, name, 4, params or {"nodes": [], "edges": []})

    def _row_version(self, pid):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT row_version FROM Partitions WHERE id = ?", (pid,)
            ).fetchone()[0]


class ConflictTests(SyncTestBase):
    """§2: version-check, конфликт возвращает обе версии целиком."""

    def test_two_devices_edit_same_partition_conflict_not_silent_overwrite(self):
        pid = self._partition()
        base = self._row_version(pid)

        # Оба устройства увезли партицию с одинаковым base_version.
        change_a = {"kind": "partition", "id": pid, "base_version": base,
                    "data": {"subject_id": self.subject_id,
                             "partition_name": "Сила F=ma",
                             "constracted": 4,
                             "generation_parametrs": {"nodes": [{"id": "a"}],
                                                      "edges": []}}}
        change_b = {"kind": "partition", "id": pid, "base_version": base,
                    "data": {"subject_id": self.subject_id,
                             "partition_name": "Сила F=ma",
                             "constracted": 4,
                             "generation_parametrs": {"nodes": [{"id": "b"}],
                                                      "edges": []}}}

        # Устройство A успевает первым — принято, версия выросла.
        out_a = sync_api.push(self.repo, device_id="dev-a", user_id=None,
                              changed_entities=[change_a])
        self.assertEqual(len(out_a["accepted"]), 1)
        self.assertEqual(out_a["conflicts"], [])
        ver_after_a = out_a["accepted"][0]["row_version"]
        self.assertGreater(ver_after_a, base)

        # Устройство B с тем же base_version — конфликт, НЕ перезапись.
        out_b = sync_api.push(self.repo, device_id="dev-b", user_id=None,
                              changed_entities=[change_b])
        self.assertEqual(out_b["accepted"], [])
        self.assertEqual(len(out_b["conflicts"]), 1)
        conflict = out_b["conflicts"][0]
        # Обе версии целиком: моя — правка B, серверная — правка A.
        self.assertEqual(
            conflict["mine"]["generation_parametrs"]["nodes"], [{"id": "b"}])
        self.assertEqual(
            conflict["theirs"]["generation_parametrs"]["nodes"], [{"id": "a"}])
        self.assertEqual(conflict["theirs"]["row_version"], ver_after_a)

        # На сервере осталась версия A — тихой перезаписи не случилось.
        part = self.repo.get_partition(pid)
        self.assertEqual(part.generation_params["nodes"], [{"id": "a"}])

    def test_matching_base_version_accepts_and_bumps(self):
        pid = self._partition()
        base = self._row_version(pid)
        out = sync_api.push(self.repo, device_id="dev-a", user_id=None,
                            changed_entities=[{
                                "kind": "partition", "id": pid,
                                "base_version": base,
                                "data": {"subject_id": self.subject_id,
                                         "partition_name": "Переименовано",
                                         "constracted": 4,
                                         "generation_parametrs": {}}}])
        self.assertEqual(len(out["accepted"]), 1)
        self.assertEqual(self.repo.get_partition(pid).name, "Переименовано")

    def test_offline_created_entity_gets_server_id_via_local_ref(self):
        out = sync_api.push(self.repo, device_id="dev-a", user_id=None,
                            changed_entities=[{
                                "kind": "partition", "id": None,
                                "base_version": 0, "local_ref": "tmp-17",
                                "data": {"subject_id": self.subject_id,
                                         "partition_name": "Новый офлайн",
                                         "constracted": 0,
                                         "generation_parametrs": ""}}])
        acc = out["accepted"][0]
        self.assertTrue(acc["created"])
        self.assertEqual(acc["local_ref"], "tmp-17")
        self.assertIsNotNone(self.repo.get_partition(acc["id"]))

    def test_conflicting_delete_is_reported_not_applied(self):
        pid = self._partition()
        base = self._row_version(pid)
        # Кто-то отредактировал позже…
        self._partition(params={"nodes": [{"id": "x"}], "edges": []})
        # …а устройство пытается удалить от старой версии.
        out = sync_api.push(self.repo, device_id="dev-a", user_id=None,
                            changed_entities=[{
                                "kind": "partition", "id": pid,
                                "base_version": base, "deleted": True}])
        self.assertEqual(len(out["conflicts"]), 1)
        self.assertIsNotNone(self.repo.get_partition(pid), "не удалилась")


class TombstoneTests(SyncTestBase):
    """§2: удаление — tombstone; второе устройство получает его в pull."""

    def test_tombstone_reaches_second_device_as_deletion(self):
        pid = self._partition()
        # Устройство B полностью синхронизировано.
        _, cursors_b = _pull_all(self.repo, "dev-b")

        # Устройство A удаляет (через обычный API удаления).
        self.repo.delete_partition(pid)

        # B тянет диф — удаление приходит tombstone'ом, не молчанием.
        agg, cursors_b = _pull_all(self.repo, "dev-b", cursors_b)
        deleted = [d for d in agg["deleted"] if d["kind"] == "partition"]
        self.assertEqual([d["id"] for d in deleted], [pid])
        # Живой копии в дифе нет.
        self.assertNotIn(pid, [p["id"] for p in agg["partitions"]])

        # Повторный pull с новыми курсорами пуст (диф не залипает).
        agg2, _ = _pull_all(self.repo, "dev-b", cursors_b)
        self.assertEqual(agg2["deleted"], [])
        self.assertEqual(agg2["partitions"], [])

    def test_delete_via_push_tombstones_row(self):
        pid = self._partition()
        base = self._row_version(pid)
        out = sync_api.push(self.repo, device_id="dev-a", user_id=None,
                            changed_entities=[{
                                "kind": "partition", "id": pid,
                                "base_version": base, "deleted": True}])
        self.assertTrue(out["accepted"][0]["deleted"])
        self.assertIsNone(self.repo.get_partition(pid), "скрыта из API")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT deleted_at FROM Partitions WHERE id = ?", (pid,)
            ).fetchone()
        self.assertIsNotNone(row, "строка живёт как tombstone")
        self.assertIsNotNone(row[0])


class AttemptIdempotencyTests(SyncTestBase):
    """§3: телеметрия — идемпотентный append по client_uuid."""

    def test_double_send_of_same_attempt_is_not_duplicated(self):
        pid = self._partition()
        attempt = {"client_uuid": "11111111-2222-3333-4444-555555555555",
                   "partition_id": pid, "payload": {"answer": "42"},
                   "correct": True, "created_at": 1000.0}

        out1 = sync_api.push(self.repo, device_id="dev-a", user_id="alla",
                             attempts=[attempt])
        self.assertEqual(out1["attempts_new"], 1)

        # Обрыв сети → устройство шлёт тот же пакет повторно.
        out2 = sync_api.push(self.repo, device_id="dev-a", user_id="alla",
                             attempts=[attempt])
        self.assertEqual(out2["attempts_received"], 1)
        self.assertEqual(out2["attempts_new"], 0, "дубль не вставился")

        with sqlite3.connect(self.db_path) as conn:
            n = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        self.assertEqual(n, 1)

    def test_word_stats_deltas_are_summed(self):
        delta = {"term": "cat", "shown": 3, "correct": 2, "wrong": 1,
                 "last_seen": 500.0}
        sync_api.push(self.repo, device_id="dev-a", user_key="u1",
                      user_id=None, word_stats_deltas=[delta])
        sync_api.push(self.repo, device_id="dev-b", user_key="u1",
                      user_id=None,
                      word_stats_deltas=[{"term": "cat", "shown": 1,
                                          "correct": 0, "wrong": 1,
                                          "last_seen": 900.0}])
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT times_shown, times_correct, times_wrong, last_seen "
                "FROM WordStats WHERE user_id = 'u1' AND term = 'cat'"
            ).fetchone()
        self.assertEqual((row[0], row[1], row[2]), (4, 2, 2))
        self.assertEqual(row[3], 900.0)


class CursorPaginationTests(SyncTestBase):
    """§4: диф страницами, без потерь и дублей между страницами."""

    def test_pagination_neither_loses_nor_duplicates(self):
        pids = [self._partition(name=f"Раздел {i}") for i in range(25)]

        collected: list[int] = []
        cursors: dict = {}
        pages = 0
        while True:
            out = sync_api.pull(self.repo, device_id="dev-b", user_id=None,
                                cursors=cursors, limit=10)
            collected.extend(p["id"] for p in out["partitions"])
            cursors = out["new_cursors"]
            pages += 1
            if not out["has_more"]:
                break

        self.assertGreaterEqual(pages, 3, "точно было несколько страниц")
        self.assertEqual(len(collected), len(set(collected)), "без дублей")
        self.assertEqual(set(collected), set(pids), "без потерь")

    def test_edit_advances_cursor_and_row_versions_stay_unique(self):
        pids = [self._partition(name=f"Р{i}") for i in range(5)]
        _, cursors = _pull_all(self.repo, "dev-b")

        # Правка «старой» партиции получает НОВУЮ максимальную версию —
        # диф по курсору её видит (в этом смысл глобальной монотонности).
        self.repo.upsert_partition(self.subject_id, "Р2", 0, {"v": 2})
        agg, _ = _pull_all(self.repo, "dev-b", cursors)
        self.assertEqual([p["id"] for p in agg["partitions"]], [pids[2]])

        with sqlite3.connect(self.db_path) as conn:
            n, uniq = conn.execute(
                "SELECT COUNT(row_version), COUNT(DISTINCT row_version) "
                "FROM Partitions"
            ).fetchone()
        self.assertEqual(n, uniq, "row_version уникальны в пределах таблицы")

    def test_migration_002_uniquifies_preexisting_versions(self):
        # Имитируем «до-миграционные» дубли версий и прогоняем 002 повторно
        # (идемпотентность раннёра здесь не при чём — функция чистая).
        from core.migrations import _m002_sync_protocol
        self._partition(name="A")
        self._partition(name="B")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE Partitions SET row_version = 1")
            _m002_sync_protocol(conn)
            n, uniq = conn.execute(
                "SELECT COUNT(row_version), COUNT(DISTINCT row_version) "
                "FROM Partitions"
            ).fetchone()
        self.assertEqual(n, uniq)


class ScopeTests(SyncTestBase):
    """Область pull: со скоупом чужое живое не отдаётся, tombstones — всем."""

    def test_scope_filters_alive_rows(self):
        # Чужой предмет (owner=логин «boris») и партиция в нём.
        other_subject = self.repo.create_subject("Чужой", "Чужой",
                                                 owner_user_id="boris")
        self.repo.upsert_partition(other_subject, "Чужая партиция", 0, {})
        mine = self._partition(name="Моя")

        # teacher «alla»: видит системные (owner NULL) — «Физика», но не
        # предмет владельца «boris».
        out = sync_api.pull(self.repo, device_id="d", user_id="alla",
                            role="teacher", cursors={})
        subj_ids = [s["id"] for s in out["subjects"]]
        part_ids = [p["id"] for p in out["partitions"]]
        self.assertIn(self.subject_id, subj_ids)
        self.assertNotIn(other_subject, subj_ids)
        self.assertIn(mine, part_ids)
        self.assertNotIn("Чужая партиция",
                         [p["partition_name"] for p in out["partitions"]])

    def test_pull_reports_catalog_version_resource(self):
        out = sync_api.pull(self.repo, device_id="d", user_id=None, cursors={})
        self.assertTrue(out["resources"]["catalog_version"])


if __name__ == "__main__":
    unittest.main()
