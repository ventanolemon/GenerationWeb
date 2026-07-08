"""
Проверка фундамента RBAC + миграции БД (Фаза 1).

Запуск без pytest (в целевом окружении его нет — слой core обязан
проверяться на голом stdlib):

    python core/test_rbac_migration.py

Проверяет:
  1. Свежая БД: миграция создаёт все таблицы и users в целевой форме;
     повторный прогон идемпотентен.
  2. Унаследованная БД (старая форма users с plaintext-паролем): миграция
     сохраняет данные, назначает числовой id, роль student; вход по
     исходному паролю работает и апгрейдит хеш до pbkdf2.
  3. Пароли: pbkdf2 round-trip, неверный пароль отклоняется, legacy
     sha256(login:password) принимается и просит апгрейд.
  4. Владение/видимость: системный предмет редактирует только admin,
     свой — владелец; visible_subject_ids скоупит верно.
  5. Группы: создание, участник, привязка преподавателя.
  6. Sync: row_version партиции растёт при повторном upsert.
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.repository import Repository, ROLES  # noqa: E402
from core.passwords import hash_password, verify_password, _legacy_sha256  # noqa: E402
from core.migrations import run_migrations, applied_versions  # noqa: E402


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # Repository создаст заново
    return path


_EXPECTED_TABLES = {
    "users", "Subjects", "Partitions", "groups", "group_members",
    "teacher_groups", "assignments", "attempts", "devices",
    "contour_jobs", "corpus_records", "schema_migrations",
}


def test_fresh_db_and_idempotency():
    path = _tmp_db()
    try:
        Repository(path)  # прогоняет миграции в _init_db
        with sqlite3.connect(path) as conn:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert _EXPECTED_TABLES <= tables, f"нет таблиц: {_EXPECTED_TABLES - tables}"
            ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            assert {"id", "role", "password_hash"} <= ucols, ucols
            scols = {r[1] for r in conn.execute("PRAGMA table_info(Subjects)")}
            assert {"owner_user_id", "row_version", "deleted_at"} <= scols, scols
            # Идемпотентность: повторный прогон не добавляет версий и не падает.
            before = applied_versions(conn)
            again = run_migrations(conn)
            after = applied_versions(conn)
            assert again == [], f"повторный прогон применил миграции: {again}"
            assert before == after == {1}, (before, after)
    finally:
        os.unlink(path)


def test_legacy_db_preserved_and_upgraded():
    path = _tmp_db()
    try:
        # Симулируем «поставочную» БД: старая форма users (4 колонки,
        # plaintext-пароль), Subjects/Partitions без sync-колонок.
        with sqlite3.connect(path) as conn:
            conn.executescript(
                'CREATE TABLE users ('
                '  login TEXT PRIMARY KEY, password TEXT, FIO TEXT, "group" TEXT);'
                'CREATE TABLE Subjects ('
                '  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_name TEXT, pra_subject TEXT);'
                'CREATE TABLE Partitions ('
                '  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER,'
                '  partition_name TEXT, constracted INTEGER, generation_parametrs TEXT);'
            )
            conn.execute(
                "INSERT INTO users (login, password, FIO, \"group\") VALUES (?,?,?,?)",
                ("ventano", "2112005", "Иван", "КСБО-11-24"),
            )
            conn.execute(
                "INSERT INTO Subjects (subject_name, pra_subject) VALUES (?,?)",
                ("Линейная алгебра", "Линейная алгебра"),
            )
            conn.commit()

        repo = Repository(path)  # миграция должна пройти по существующим данным

        prof = repo.find_user("ventano", "2112005")  # вход по исходному паролю
        assert prof is not None, "вход по унаследованному plaintext-паролю не сработал"
        assert prof.login == "ventano"
        assert prof.role == "student", prof.role
        assert isinstance(prof.id, int) and prof.id > 0, prof.id
        assert prof.fio == "Иван"

        # После входа пароль должен быть перехеширован в pbkdf2, plaintext стёрт.
        with sqlite3.connect(path) as conn:
            ph, pw = conn.execute(
                "SELECT password_hash, password FROM users WHERE login='ventano'"
            ).fetchone()
        assert ph.startswith("pbkdf2_sha256$"), f"не апгрейдился: {ph[:20]}"
        assert pw == "", f"plaintext не стёрт: {pw!r}"
        # И повторный вход всё ещё работает уже по pbkdf2.
        assert repo.find_user("ventano", "2112005") is not None
        assert repo.find_user("ventano", "wrong") is None
    finally:
        os.unlink(path)


def test_password_formats():
    # pbkdf2 round-trip
    h = hash_password("secret")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password(h, "secret", "u") == (True, False)
    assert verify_password(h, "nope", "u") == (False, False)
    # legacy plaintext (с префиксом, как после миграции) → апгрейд
    assert verify_password("legacy:2112005", "2112005", "u") == (True, True)
    assert verify_password("legacy:2112005", "x", "u") == (False, False)
    # legacy sha256(login:password) веб-формата → апгрейд
    stored = "legacy:" + _legacy_sha256("bob", "pw")
    assert verify_password(stored, "pw", "bob") == (True, True)
    assert verify_password("", "pw", "bob") == (False, False)


def test_ownership_and_visibility():
    path = _tmp_db()
    try:
        repo = Repository(path)
        repo.create_user("teach", "p", "T", "", role="teacher")
        repo.create_user("teach2", "p", "T2", "", role="teacher")
        repo.create_user("adm", "p", "A", "", role="admin")
        repo.create_user("stud", "p", "S", "", role="student")
        tid = repo.get_user_id("teach")
        t2id = repo.get_user_id("teach2")
        aid = repo.get_user_id("adm")
        sid_user = repo.get_user_id("stud")

        sys_subj = repo.ensure_subject(1, "Линейная алгебра", "Линейная алгебра")
        own_subj = repo.create_subject("Мой курс", "Мой курс", owner_user_id=tid)

        # Системный предмет: редактирует только admin.
        assert repo.subject_owner(sys_subj) is None
        assert repo.can_edit_subject(aid, "admin", sys_subj) is True
        assert repo.can_edit_subject(tid, "teacher", sys_subj) is False
        # Свой предмет: владелец да, другой преподаватель нет, student нет.
        assert repo.can_edit_subject(tid, "teacher", own_subj) is True
        assert repo.can_edit_subject(t2id, "teacher", own_subj) is False
        assert repo.can_edit_subject(sid_user, "student", own_subj) is False

        # Видимость: teach видит системный + свой, но не чужой.
        other_subj = repo.create_subject("Чужой курс", "Чужой курс", owner_user_id=t2id)
        vis = repo.visible_subject_ids(tid, "teacher")
        assert sys_subj in vis and own_subj in vis and other_subj not in vis, vis
        # admin видит все.
        assert set(repo.visible_subject_ids(aid, "admin")) >= {
            sys_subj, own_subj, other_subj
        }
    finally:
        os.unlink(path)


def test_groups():
    path = _tmp_db()
    try:
        repo = Repository(path)
        repo.create_user("t", "p", "T", "", role="teacher")
        repo.create_user("s1", "p", "S1", "")
        repo.create_user("s2", "p", "S2", "")
        tid = repo.get_user_id("t")
        s1 = repo.get_user_id("s1")
        s2 = repo.get_user_id("s2")

        g = repo.create_group("КСБО-11-24", created_by=tid)
        repo.add_group_member(g, s1)
        repo.add_group_member(g, s2)
        repo.add_group_member(g, s1)  # дубль игнорируется
        repo.assign_teacher_to_group(tid, g)

        assert repo.list_group_members(g) == sorted([s1, s2])
        assert repo.teacher_group_ids(tid) == [g]
        assert repo.user_group_ids(s1) == [g]
    finally:
        os.unlink(path)


def test_partition_sync_bump():
    path = _tmp_db()
    try:
        repo = Repository(path)
        sid = repo.ensure_subject(1, "Физика", "Физика")
        pid = repo.upsert_partition(sid, "Кинематика", 0, {"a": 1})
        with sqlite3.connect(path) as conn:
            rv1 = conn.execute(
                "SELECT row_version FROM Partitions WHERE id=?", (pid,)
            ).fetchone()[0]
        repo.upsert_partition(sid, "Кинематика", 0, {"a": 2})  # повторный upsert
        with sqlite3.connect(path) as conn:
            rv2, upd = conn.execute(
                "SELECT row_version, updated_at FROM Partitions WHERE id=?", (pid,)
            ).fetchone()
        assert rv1 == 1, rv1
        assert rv2 == 2, rv2
        assert upd > 0, upd
    finally:
        os.unlink(path)


_TESTS = [
    test_fresh_db_and_idempotency,
    test_legacy_db_preserved_and_upgraded,
    test_password_formats,
    test_ownership_and_visibility,
    test_groups,
    test_partition_sync_bump,
]


def main() -> int:
    assert ROLES == ("student", "teacher", "admin")
    failed = 0
    for t in _TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failed}/{len(_TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
