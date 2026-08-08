"""
Выдача предметов преподавателям (docs/subject_grants.md) — серверная половина.

Проверяем то, ради чего документ и написан:
  * миграция 006: таблицы выдач/настроек, стартовая эпоха 1 (а не 0 — иначе
    клиент, который эпохи не знает, совпал бы с сервером по случайности);
  * полная замена набора вместо дельты, отзыв через неё же, инкремент эпохи;
  * режим умолчания: 'all' не ограничивает никого без выдач, 'none' —
    ограничивает всех, переключение поднимает эпоху ВСЕМ преподавателям;
  * скоуп pull'а: выдача и расширяет (чужой предмет доезжает), и сужает
    (невыданное уходит), собственные предметы не выпадают никогда, админ и
    студент не ограничиваются;
  * scope-эпоха в pull: пересборка объявляется при расхождении, приходит
    одним ответом (клиент в этом режиме шлёт пустые курсоры на каждой
    странице — пагинация не сошлась бы), не объявляется анониму;
  * роутер: 401/403, литеральный default-access не перехватывается {login}.

Запуск: python -m unittest core.test_subject_grants -v  (из корня монорепо)
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

from core import grants_api, organizations_api, sync_api  # noqa: E402
from core import auth_sessions  # noqa: E402
from core.repository import Repository  # noqa: E402


class GrantsTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)          # Repository создаст заново
        self.repo = Repository(self.db_path)
        self.repo.create_user("root", "p", "Админ", "", role="admin")
        self.repo.create_user("alla", "p", "Алла", "", role="teacher")
        self.repo.create_user("boris", "p", "Борис", "", role="teacher")
        self.repo.create_user("stud", "p", "Студент", "КСБО-11")
        # Встроенный (owner NULL) + авторский предмет каждого преподавателя.
        self.builtin = self.repo.ensure_subject(3, "Физика")
        self.alla_subject = self.repo.create_subject("Курс Аллы", "Курс Аллы",
                                                     owner_user_id="alla")
        self.boris_subject = self.repo.create_subject("Курс Бориса",
                                                      "Курс Бориса",
                                                      owner_user_id="boris")

        # Предметы преподавателей — в организации по умолчанию, как их
        # положил бы обычный путь заведения.
        for sid in (self.alla_subject, self.boris_subject):
            self.repo.set_subject_organization(
                sid, self.repo.default_organization_id())

    def tearDown(self):
        os.unlink(self.db_path)

    def _default_access(self, value):
        """
        Умолчание видимости — настройка ОРГАНИЗАЦИИ (§8.1), а не
        развёртывания: выдачи работают внутри организации, значит и
        умолчание для них живёт там же. `set_default_subject_access`
        остался значением для новых организаций и для тех, кто вне их.
        """
        self.repo.set_organization_default_access(
            self.repo.default_organization_id(), value)


# ---------- Схема ----------

class SchemaTests(GrantsTestBase):
    def test_migration_creates_tables_and_index(self):
        with sqlite3.connect(self.db_path) as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            )}
        self.assertIn("subject_grants", names)
        self.assertIn("app_settings", names)
        self.assertIn("ix_subject_grants_subject", names)

    def test_scope_version_starts_at_one_not_zero(self):
        # Клиент, эпохи не знающий, шлёт 0 — и обязан получить пересборку.
        self.assertEqual(self.repo.scope_version("alla"), 1)

    def test_scope_version_of_unknown_user_is_zero(self):
        self.assertEqual(self.repo.scope_version("нет-такого"), 0)
        self.assertEqual(self.repo.scope_version(None), 0)

    def test_migration_is_idempotent(self):
        from core.migrations import _m006_subject_grants
        with sqlite3.connect(self.db_path) as conn:
            _m006_subject_grants(conn)
            _m006_subject_grants(conn)
        self.assertEqual(self.repo.scope_version("alla"), 1)


# ---------- Repository ----------

class RepositoryGrantsTests(GrantsTestBase):
    def test_replace_is_full_not_delta(self):
        self.repo.replace_subject_grants("alla", [self.builtin,
                                                  self.boris_subject])
        self.assertEqual(self.repo.subject_grants("alla"),
                         sorted([self.builtin, self.boris_subject]))
        # Вторая запись ЗАМЕЩАЕТ набор целиком — так и снимается доступ.
        self.repo.replace_subject_grants("alla", [self.builtin])
        self.assertEqual(self.repo.subject_grants("alla"), [self.builtin])
        self.repo.replace_subject_grants("alla", [])
        self.assertEqual(self.repo.subject_grants("alla"), [])

    def test_replace_dedupes_and_sorts(self):
        self.repo.replace_subject_grants(
            "alla", [self.builtin, self.builtin, self.alla_subject])
        self.assertEqual(self.repo.subject_grants("alla"),
                         sorted([self.builtin, self.alla_subject]))

    def test_replace_bumps_scope_version_every_time(self):
        before = self.repo.scope_version("alla")
        v1 = self.repo.replace_subject_grants("alla", [self.builtin])
        v2 = self.repo.replace_subject_grants("alla", [self.builtin])
        self.assertEqual(v1, before + 1)
        # Тот же набор — эпоха всё равно растёт: сверять ради экономии одной
        # идемпотентной пересборки дороже, чем её пережить.
        self.assertEqual(v2, before + 2)

    def test_replace_touches_only_target_teacher(self):
        before = self.repo.scope_version("boris")
        self.repo.replace_subject_grants("alla", [self.builtin])
        self.assertEqual(self.repo.scope_version("boris"), before)

    def test_grants_of_deleted_subject_are_not_returned(self):
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE Subjects SET deleted_at = 1 WHERE id = ?",
                         (self.boris_subject,))
            conn.commit()
        self.assertEqual(self.repo.subject_grants("alla"), [])
        self.assertEqual(self.repo.all_subject_grants(), {})

    def test_all_grants_returns_matrix(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        self.repo.replace_subject_grants("boris", [self.builtin,
                                                   self.alla_subject])
        self.assertEqual(
            self.repo.all_subject_grants(),
            {"alla": [self.builtin],
             "boris": sorted([self.builtin, self.alla_subject])})

    def test_default_access_roundtrip_and_validation(self):
        # Настройка РАЗВЁРТЫВАНИЯ: после §8 она осталась значением для новых
        # организаций и для тех, кто вне их. Действующее для человека
        # умолчание считает effective_default_access.
        self.assertEqual(self.repo.default_subject_access(), "all")
        self.repo.set_default_subject_access("none")
        self.assertEqual(self.repo.default_subject_access(), "none")
        with self.assertRaises(ValueError):
            self.repo.set_default_subject_access("maybe")

    def test_unknown_stored_default_access_reads_as_permissive(self):
        # Кривая настройка не должна запирать витрину.
        self.repo.set_setting("default_subject_access", "strict-ish")
        self.assertEqual(self.repo.default_subject_access(), "all")

    def test_default_access_switch_bumps_every_teacher(self):
        teachers_before = {t: self.repo.scope_version(t)
                           for t in ("alla", "boris")}
        student_before = self.repo.scope_version("stud")
        organizations_api.set_default_access(
            self.repo, org_id=self.repo.default_organization_id(),
            value="none")
        for t, before in teachers_before.items():
            self.assertEqual(self.repo.scope_version(t), before + 1)
        # Студент — участник той же организации, и его эпоха тоже растёт:
        # переключение меняет набор всем, а «выдачи только про teacher» —
        # свойство granted_scope, а не повод не сообщать об изменении.
        self.assertGreaterEqual(self.repo.scope_version("stud"),
                                student_before)

    def test_owned_subject_ids(self):
        self.assertEqual(self.repo.owned_subject_ids("alla"),
                         [self.alla_subject])
        self.assertEqual(self.repo.owned_subject_ids(None), [])


# ---------- Доменная логика ----------

class MyGrantsTests(GrantsTestBase):
    def test_teacher_sees_own_grants_and_mode(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        self._default_access("none")
        out = grants_api.my_grants(self.repo, actor_login="alla",
                                   role="teacher")
        self.assertEqual(out["subject_ids"], [self.builtin])
        self.assertEqual(out["default_access"], "none")
        self.assertEqual(out["scope_version"], self.repo.scope_version("alla"))

    def test_non_teacher_is_never_restricted(self):
        # Даже в строгом режиме: применивший снимок без разбора роли клиент
        # не должен запереть админа в пустой витрине.
        self._default_access("none")
        for role in ("admin", "student"):
            out = grants_api.my_grants(self.repo, actor_login="root",
                                       role=role)
            self.assertEqual(out["default_access"], "all")
            self.assertEqual(out["subject_ids"], [])


class GrantedScopeTruthTableTests(GrantsTestBase):
    """Та же таблица истинности, что у GrantsSnapshot.restricts на десктопе:
    разъедься половины — витрина и скоуп pull'а разойдутся."""

    def _scope(self, login="alla", role="teacher"):
        return grants_api.granted_scope(self.repo, login, role)

    def test_all_without_grants_does_not_restrict(self):
        self.assertIsNone(self._scope())

    def test_all_with_grants_restricts_to_them(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        self.assertEqual(self._scope(), {self.builtin})

    def test_none_without_grants_restricts_to_nothing(self):
        self._default_access("none")
        self.assertEqual(self._scope(), set())

    def test_non_teacher_and_guest_never_restricted(self):
        self._default_access("none")
        self.repo.replace_subject_grants("alla", [self.builtin])
        self.assertIsNone(self._scope(role="admin"))
        self.assertIsNone(self._scope(role="student"))
        self.assertIsNone(self._scope(login=None))


class AdminMatrixTests(GrantsTestBase):
    def test_matrix_has_teachers_subjects_and_grants(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        m = grants_api.admin_matrix(self.repo)
        self.assertEqual(m["default_access"], "all")
        self.assertEqual({t["login"] for t in m["teachers"]},
                         {"alla", "boris"})
        builtin = next(s for s in m["subjects"] if s["id"] == self.builtin)
        authored = next(s for s in m["subjects"]
                        if s["id"] == self.alla_subject)
        self.assertTrue(builtin["is_builtin"])
        self.assertFalse(authored["is_builtin"])
        # Преподаватель без выдач присутствует пустым списком: иначе клиент
        # не отличит «ничего не выдано» от «строка не загружена».
        self.assertEqual(m["grants"]["alla"], [self.builtin])
        self.assertEqual(m["grants"]["boris"], [])

    def test_matrix_lists_only_teachers(self):
        logins = {t["login"] for t in
                  grants_api.admin_matrix(self.repo)["teachers"]}
        self.assertNotIn("root", logins)
        self.assertNotIn("stud", logins)


class SetGrantsValidationTests(GrantsTestBase):
    def _set(self, login, ids):
        return grants_api.set_teacher_grants(
            self.repo, actor_login="root", target_login=login, subject_ids=ids)

    def test_happy_path_records_author_and_returns_version(self):
        out = self._set("alla", [self.builtin])
        self.assertTrue(out["ok"])
        self.assertEqual(out["subject_ids"], [self.builtin])
        self.assertEqual(out["scope_version"], self.repo.scope_version("alla"))
        with sqlite3.connect(self.db_path) as conn:
            granted_by = conn.execute(
                "SELECT granted_by FROM subject_grants "
                "WHERE teacher_login = ?", ("alla",)).fetchone()[0]
        self.assertEqual(granted_by, "root")

    def test_unknown_user_rejected(self):
        with self.assertRaisesRegex(grants_api.GrantActionError, "не найден"):
            self._set("нет-такого", [])

    def test_non_teacher_rejected(self):
        with self.assertRaisesRegex(grants_api.GrantActionError,
                                    "преподавател"):
            self._set("stud", [])

    def test_unknown_subject_rejected(self):
        # Мёртвая строка, которую потом никто не найдёт, хуже явной ошибки.
        with self.assertRaisesRegex(grants_api.GrantActionError, "9999"):
            self._set("alla", [self.builtin, 9999])

    def test_non_numeric_ids_rejected(self):
        with self.assertRaises(grants_api.GrantActionError):
            self._set("alla", ["физика"])

    def test_set_default_access_validates(self):
        with self.assertRaises(grants_api.GrantActionError):
            grants_api.set_default_access(self.repo, default_access="maybe")
        out = grants_api.set_default_access(self.repo, default_access="none")
        self.assertEqual(out["default_access"], "none")
        self.assertEqual(self.repo.default_subject_access(), "none")


class RoleChangeTests(GrantsTestBase):
    def test_role_change_bumps_scope_epoch(self):
        from core import admin_api
        before = self.repo.scope_version("alla")
        admin_api.change_role(self.repo, actor_login="root",
                              target_login="alla", new_role="student")
        self.assertEqual(self.repo.scope_version("alla"), before + 1)


# ---------- Скоуп pull'а ----------

class SyncScopeTests(GrantsTestBase):
    def setUp(self):
        super().setUp()
        self.builtin_part = self.repo.upsert_partition(
            self.builtin, "Сила F=ma", 0, {})
        self.alla_part = self.repo.upsert_partition(
            self.alla_subject, "Раздел Аллы", 0, {})
        self.boris_part = self.repo.upsert_partition(
            self.boris_subject, "Раздел Бориса", 0, {})

    def _pull(self, login, role="teacher"):
        return sync_api.pull(self.repo, device_id="d", user_id=login,
                             role=role, cursors={},
                             scope_version=self.repo.scope_version(login))

    def _subject_ids(self, out):
        return {s["id"] for s in out["subjects"]}

    def test_without_grants_scope_is_plain_rbac(self):
        ids = self._subject_ids(self._pull("alla"))
        self.assertEqual(ids, {self.builtin, self.alla_subject})

    def test_grant_widens_scope_to_another_owners_subject(self):
        # Ровно то, ради чего документ и делает серверный скоуп: withhold и
        # выдача авторского контента. Без расширения выдача не удерживала бы
        # ничего, кроме встроенного.
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        out = self._pull("alla")
        self.assertIn(self.boris_subject, self._subject_ids(out))
        self.assertIn(self.boris_part, {p["id"] for p in out["partitions"]})

    def test_grant_narrows_away_builtin(self):
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        self.assertNotIn(self.builtin, self._subject_ids(self._pull("alla")))

    def test_own_subject_survives_any_grant_set(self):
        # Клиент удаляет всё, что не приехало; выпади отсюда авторский
        # контент — отзыв чужого доступа стёр бы преподавателю его работу.
        self.repo.replace_subject_grants("alla", [self.boris_subject])
        self.assertIn(self.alla_subject, self._subject_ids(self._pull("alla")))
        self.repo.replace_subject_grants("alla", [])
        self._default_access("none")
        self.assertEqual(self._subject_ids(self._pull("alla")),
                         {self.alla_subject})

    def test_strict_mode_without_grants_leaves_only_own(self):
        self._default_access("none")
        out = self._pull("boris")
        self.assertEqual(self._subject_ids(out), {self.boris_subject})
        self.assertEqual({p["id"] for p in out["partitions"]},
                         {self.boris_part})

    def test_admin_and_student_are_not_restricted(self):
        self._default_access("none")
        self.assertEqual(
            self._subject_ids(self._pull("root", role="admin")),
            {self.builtin, self.alla_subject, self.boris_subject})
        # Студент: обычный RBAC (системные), выдачи его не касаются.
        self.assertEqual(self._subject_ids(self._pull("stud", role="student")),
                         {self.builtin})

    def test_anonymous_scope_still_sees_everything(self):
        self._default_access("none")
        out = sync_api.pull(self.repo, device_id="d", user_id=None, cursors={})
        self.assertEqual(self._subject_ids(out),
                         {self.builtin, self.alla_subject,
                          self.boris_subject})

    def test_tombstones_ignore_scope(self):
        # Удаление обязано доехать, даже если предмет выпал из области.
        self._default_access("none")
        self.repo.delete_partition(self.builtin_part)
        out = self._pull("alla")
        self.assertIn(self.builtin_part,
                      {d["id"] for d in out["deleted"]})


# ---------- Scope-эпоха ----------

class ScopeEpochTests(GrantsTestBase):
    def _pull(self, login, scope_version, cursors=None, limit=200):
        return sync_api.pull(self.repo, device_id="d", user_id=login,
                             role="teacher", cursors=cursors or {},
                             limit=limit, scope_version=scope_version)

    def test_client_without_epoch_gets_rebuild(self):
        out = self._pull("alla", 0)
        self.assertTrue(out["resync"])
        self.assertEqual(out["scope_version"], 1)

    def test_matching_epoch_is_an_ordinary_diff(self):
        out = self._pull("alla", self.repo.scope_version("alla"))
        self.assertNotIn("resync", out)

    def test_grant_makes_the_next_pull_rebuild(self):
        known = self.repo.scope_version("alla")
        self.assertNotIn("resync", self._pull("alla", known))
        self.repo.replace_subject_grants("alla", [self.builtin])
        out = self._pull("alla", known)
        self.assertTrue(out["resync"])
        self.assertEqual(out["scope_version"], known + 1)

    def test_revoke_makes_the_next_pull_rebuild(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        known = self.repo.scope_version("alla")
        self.repo.replace_subject_grants("alla", [])
        self.assertTrue(self._pull("alla", known)["resync"])

    def test_rebuild_ignores_client_cursors(self):
        # Выдали предмет, чью версию курсор клиента давно прошёл: обычный диф
        # его не принесёт никогда — в этом и вся причина существования эпохи.
        stale = {"subjects": 10_000, "partitions": 10_000}
        out = self._pull("alla", 0, cursors=stale)
        self.assertTrue(out["resync"])
        self.assertIn(self.builtin, {s["id"] for s in out["subjects"]})

    def test_rebuild_comes_in_one_response_regardless_of_limit(self):
        # Клиент в режиме пересборки шлёт пустые курсоры на КАЖДОЙ странице,
        # а сервер stateless — разбитая на страницы пересборка не сошлась бы.
        for i in range(25):
            self.repo.upsert_partition(self.builtin, f"Раздел {i}", 0, {})
        out = self._pull("alla", 0, limit=10)
        self.assertTrue(out["resync"])
        self.assertFalse(out["has_more"])
        self.assertEqual(len(out["partitions"]), 25)

    def test_ordinary_diff_still_pages(self):
        for i in range(25):
            self.repo.upsert_partition(self.builtin, f"Раздел {i}", 0, {})
        out = self._pull("alla", self.repo.scope_version("alla"), limit=10)
        self.assertTrue(out["has_more"])
        self.assertEqual(len(out["partitions"]), 10)

    def test_anonymous_client_is_never_told_to_rebuild(self):
        out = sync_api.pull(self.repo, device_id="d", user_id=None,
                            cursors={}, scope_version=0)
        self.assertNotIn("resync", out)
        self.assertEqual(out["scope_version"], 0)

    def test_default_access_switch_rebuilds_every_teacher(self):
        known = {t: self.repo.scope_version(t) for t in ("alla", "boris")}
        organizations_api.set_default_access(
            self.repo, org_id=self.repo.default_organization_id(),
            value="none")
        for t, v in known.items():
            self.assertTrue(self._pull(t, v)["resync"])

    def test_desktop_pull_loop_terminates_on_rebuild(self):
        """
        Реальный цикл десктопа (core/sync/client.py `_pull`), а не идеальный:
        начав пересборку, он шлёт ПУСТЫЕ курсоры и СТАРУЮ эпоху на каждой
        следующей странице — эпоху он сохраняет лишь после чистки. Сервер
        stateless, страницы отличить не может, поэтому пагинированная
        пересборка крутилась бы вечно. Здесь фиксируем, что не крутится и
        что клиент видит полный набор — на этом держится корректность его
        чистки.
        """
        for i in range(25):
            self.repo.upsert_partition(self.builtin, f"Раздел {i}", 0, {})
        known = 0                      # свежий клиент эпохи не знает
        cursors: dict = {}
        resyncing = False
        seen: set[int] = set()
        pages = 0
        while True:
            out = self._pull("alla", known,
                             cursors={} if resyncing else cursors, limit=10)
            if out.get("resync"):
                resyncing = True
            seen.update(p["id"] for p in out["partitions"])
            cursors = out["new_cursors"]
            pages += 1
            self.assertLess(pages, 5, "цикл пересборки не сходится")
            if not out["has_more"]:
                break
        self.assertEqual(pages, 1)
        self.assertEqual(len(seen), 25)
        # Курсор после пересборки — максимальный, обычный диф продолжится с него.
        self.assertNotIn("resync",
                         self._pull("alla", self.repo.scope_version("alla"),
                                    cursors=cursors))


# ---------- Роутер ----------

class RouterTests(GrantsTestBase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from generator_service.routers import grants as grants_router

        app = FastAPI()
        app.include_router(grants_router.router)
        app.state.repo = self.repo
        return TestClient(app)

    def _h(self, login, role=None):
        """
        Заголовки личности: настоящая сессия, а не заявление.

        Роль больше не передаётся — сервер читает её из БД по токену
        (GEN_TRUST_IDENTITY_HEADERS снят). Параметр оставлен, чтобы не
        переписывать сотни вызовов, и игнорируется: если он расходится с
        БД, прав это не добавляет — в этом и была суть перехода.
        """
        token = auth_sessions.issue(self.repo, login)["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_mine_requires_identity(self):
        self.assertEqual(
            self._client().get("/subjects/grants/mine").status_code, 401)

    def test_mine_returns_snapshot(self):
        self.repo.replace_subject_grants("alla", [self.builtin])
        r = self._client().get("/subjects/grants/mine",
                               headers=self._h("alla", "teacher"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["subject_ids"], [self.builtin])
        self.assertEqual(r.json()["default_access"], "all")

    def test_admin_endpoints_reject_teacher(self):
        c = self._client()
        h = self._h("alla", "teacher")
        self.assertEqual(c.get("/admin/subject-grants", headers=h).status_code,
                         403)
        self.assertEqual(
            c.put("/admin/subject-grants/alla", json={"subject_ids": []},
                  headers=h).status_code, 403)
        self.assertEqual(
            c.put("/admin/subject-grants/default-access",
                  json={"default_access": "none"}, headers=h).status_code, 403)

    def test_admin_matrix_and_put_flow(self):
        c = self._client()
        h = self._h("root", "admin")
        r = c.put("/admin/subject-grants/alla",
                  json={"subject_ids": [self.builtin, self.builtin]},
                  headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["subject_ids"], [self.builtin])
        self.assertEqual(r.json()["scope_version"],
                         self.repo.scope_version("alla"))
        m = c.get("/admin/subject-grants", headers=h).json()
        self.assertEqual(m["grants"]["alla"], [self.builtin])

    def test_default_access_route_is_not_captured_by_login_route(self):
        # Литерал объявлен выше {login} — иначе режим умолчания стал бы
        # выдачей преподавателю с логином «default-access».
        c = self._client()
        r = c.put("/admin/subject-grants/default-access",
                  json={"default_access": "none"},
                  headers=self._h("root", "admin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["default_access"], "none")
        # Настройка теперь у ОРГАНИЗАЦИИ вызывающего, а не одна на
        # развёртывание: выдачи работают внутри организации (§8.1).
        self.assertEqual(self.repo.effective_default_access("root"), "none")

    def test_bad_payloads_return_400(self):
        c = self._client()
        h = self._h("root", "admin")
        self.assertEqual(
            c.put("/admin/subject-grants/default-access",
                  json={"default_access": "maybe"}, headers=h).status_code, 400)
        self.assertEqual(
            c.put("/admin/subject-grants/stud", json={"subject_ids": []},
                  headers=h).status_code, 400)
        self.assertEqual(
            c.put("/admin/subject-grants/alla", json={"subject_ids": [9999]},
                  headers=h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
