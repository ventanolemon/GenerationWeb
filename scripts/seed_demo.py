"""
Демо-наполнение БД для просмотра интерфейсов (аналитика, админка, домашки,
контур, корпус). Идемпотентно — можно запускать повторно.

    python -m scripts.seed_demo            # из корня монорепо

Что наполняется:
  * Основная БД (resources/users_database.db, через Repository):
    пользователи с ролями (admin/teacher/student), группы и членство,
    попытки за 30 дней (для аналитики) и домашки (assignments).
  * БД контура (resources/contour_demo.db, через contour_service):
    джобы контура в разных статусах + записи корпуса + курация.
    Чтобы contour_service работал на этих данных, поднимайте его с
    CONTOUR_DB_PATH=resources/contour_demo.db (см. вывод скрипта).

Демо-логины (пароли): root / elena_admin — admin (admin123);
alla / boris — teacher (teach123); s_* — student (stud123).
"""

from __future__ import annotations

import hashlib
import random
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from const import DB_PATH, RESOURCES_DIR  # noqa: E402
from core import Repository  # noqa: E402

DAY = 86400.0
RND = random.Random(20260721)  # детерминизм: повторный прогон — те же данные

# ── Демо-люди ────────────────────────────────────────────────────────────────
ADMINS = [("root", "Смирнов А. К."), ("elena_admin", "Егорова Е. В.")]
TEACHERS = [("alla", "Иванова А. С."), ("boris", "Петров Б. Н.")]
# (логин, ФИО, группа, «сила» студента 0..1 — базовая доля верных)
STUDENTS = [
    ("s_ivanov", "Иванов И. А.", "КСБО-11-24", 0.58),
    ("s_petrova", "Петрова М. С.", "КСБО-11-24", 0.88),
    ("s_orlova", "Орлова Т. М.", "КСБО-11-24", 0.91),
    ("s_sidorov", "Сидоров А. В.", "КСБО-12-24", 0.66),
    ("s_morozov", "Морозов Д. И.", "КСБО-12-24", 0.43),
    ("s_pavlov", "Павлов К. Н.", "КСБО-12-24", 0.35),
    ("s_kozlova", "Козлова Е. Д.", "ИСТ-21-24", 0.79),
    ("s_volkova", "Волкова Н. П.", "ИСТ-21-24", 0.74),
]
# Партиции для попыток (id из resources/users_database.db) + «сложность»
# (множитель доли верных: <1 — тяжелее). Реальные разделы из seed'а проекта.
TASKS = [
    (8, 0.95), (14, 0.75), (16, 1.05), (20, 1.15),
    (21, 0.9), (24, 1.0), (28, 0.7), (29, 0.85),
]


def seed_main() -> None:
    repo = Repository(DB_PATH)

    # 1. Пользователи + роли (create_user авто-заводит группу по метке).
    for login, fio in ADMINS:
        repo.create_user(login, "admin123", fio, "", role="admin")
        repo.set_user_role(login, "admin")
    for login, fio in TEACHERS:
        repo.create_user(login, "teach123", fio, "", role="teacher")
        repo.set_user_role(login, "teacher")
    for login, fio, group, _ in STUDENTS:
        repo.create_user(login, "stud123", fio, group, role="student")
        repo.set_user_role(login, "student")

    # 2. Преподаватели → группы (alla ведёт КСБО-11/12, boris — ИСТ-21).
    def gid(name: str) -> int:
        g = repo.group_by_name(name)
        return g.id if g else repo.create_group(name, created_by="root")

    for name in ("КСБО-11-24", "КСБО-12-24"):
        repo.assign_teacher_to_group("alla", gid(name))
    repo.assign_teacher_to_group("boris", gid("ИСТ-21-24"))

    # 3. Домашки: выдаём несколько заданий группам (для экрана «Домашки»).
    now = time.time()
    assignments = {
        repo.create_assignment(8, gid("КСБО-11-24"), "alla", now + 5 * DAY): ("s_ivanov", "s_petrova", "s_orlova"),
        repo.create_assignment(28, gid("КСБО-12-24"), "alla", now + 3 * DAY): ("s_sidorov", "s_morozov", "s_pavlov"),
        repo.create_assignment(21, gid("ИСТ-21-24"), "boris", None): ("s_kozlova", "s_volkova"),
    }

    # 4. Попытки за 30 дней — топливо аналитики. Детерминированный client_uuid
    #    → INSERT OR IGNORE делает повторный прогон безопасным.
    rows: list[tuple] = []
    for login, fio, group, skill in STUDENTS:
        for pid, diff in TASKS:
            # у каждого студента своя активность по заданию
            n = RND.randint(3, 14)
            rate = max(0.05, min(0.98, skill * diff))
            for k in range(n):
                day = RND.randint(0, 29)
                ts = now - day * DAY - RND.uniform(0, DAY)
                correct = 1 if RND.random() < rate else 0
                cuid = f"seed-{login}-{pid}-{k}"
                # если попытка попадает в домашку этой группы — привяжем
                aid = next((a for a, members in assignments.items()
                            if login in members and _assignment_pid(repo, a) == pid), None)
                rows.append((cuid, login, pid, aid, correct, ts))

    with repo._connect() as conn:  # noqa: SLF001 — seed-скрипт, слой данных
        conn.executemany(
            "INSERT OR IGNORE INTO attempts "
            "(client_uuid, user_id, partition_id, assignment_id, payload, correct, created_at) "
            "VALUES (?, ?, ?, ?, '', ?, ?)",
            rows,
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    print(f"[main] пользователей: {len(ADMINS)+len(TEACHERS)+len(STUDENTS)}, "
          f"попыток в attempts: {total}, домашек: {len(assignments)}")


_ASSIGN_PID_CACHE: dict[int, int] = {}


def _assignment_pid(repo: Repository, assignment_id: int) -> int:
    if assignment_id not in _ASSIGN_PID_CACHE:
        a = repo.get_assignment(assignment_id)
        _ASSIGN_PID_CACHE[assignment_id] = a.partition_id if a else -1
    return _ASSIGN_PID_CACHE[assignment_id]


# ── Контур + корпус (отдельная БД, реальные code-paths сервиса) ───────────────

def seed_contour() -> None:
    from contour_service.db import apply_migrations, connect_sqlite
    from contour_service.corpus import CorpusStore
    from contour_service.queue import SqliteJobQueue
    from core import graph_api
    from core.graph_probe import probe_graph
    from exercises.graph_examples import EXAMPLES

    contour_db = RESOURCES_DIR / "contour_demo.db"
    conn = connect_sqlite(contour_db)
    apply_migrations(conn)
    queue = SqliteJobQueue(conn)
    corpus = CorpusStore(conn)

    graph = EXAMPLES["physics_force"]["graph"]
    probe = probe_graph(graph)                     # НАСТОЯЩИЙ probe-отчёт
    catalog = graph_api.catalog_version()

    accept = {"verdict": "accept", "confidence": 0.93, "failures": [],
              "summary": "Ответ выводится из условия, разнообразие полное, "
                         "провалов не найдено."}
    revise = {"verdict": "revise", "confidence": 0.7,
              "failures": [{"code": "B4", "severity": "warn",
                            "evidence": "distinct_answers=2/8",
                            "detail": "низкое разнообразие ответов"}],
              "summary": "Разнообразие ниже порога — стоит расширить пул."}

    # Джобы в разных статусах (владелец — alla; admin видит все).
    demo = [
        ("Сила F=ma по физике: случайные массы и ускорения", "awaiting_human", accept),
        ("Кинематика: равноускоренное движение, найти путь", "awaiting_human", revise),
        ("Импульс тела: подобрать массу и скорость", "queued", None),
        ("Второй закон Ньютона: система из двух тел", "approved", accept),
        ("Замечательные пределы: выбор из пула", "rejected", None),
    ]
    made = 0
    existing = {j["description"]: j["id"]
                for j in queue.list_for_user("alla", "admin")}
    for desc, status, critic in demo:
        # идемпотентность: не плодим одинаковые описания
        if desc in existing:
            continue
        job_id = queue.enqueue(created_by="alla", subject_id=6, description=desc,
                               constraints={"task_type": "static"})
        existing[desc] = job_id
        if status == "queued":
            made += 1
            continue
        fields: dict = {"status": status,
                        "rounds": [{"round": 1, "graph": graph}]}
        if status in ("awaiting_human", "approved"):
            fields.update(result_graph=graph, result_probe=probe, critic=critic)
        if status == "rejected":
            fields.update(error="слишком просто — отклонено человеком")
        queue.update(job_id, **fields)
        made += 1

    # Корпус: записи ссылаются FK на contour_jobs — привязываем к реальной
    # джобе (approved). Любой существующий job_id удовлетворяет FK.
    backing = existing.get("Второй закон Ньютона: система из двух тел") \
        or next(iter(existing.values()))

    # Разные примеры графов → разные graph_hash (обходим дедуп) и разные
    # probe-флаги (наполняют чарт кодов таксономии). tags — «категория».
    catalog_examples = [
        ("physics_force", "Сила F=ma: случайные массы и ускорения", ["physics", "vtuz"]),
        ("derivative_poly", "Производная многочлена в точке", ["symbolic", "matan"]),
        ("limit_rational", "Предел рациональной функции", ["symbolic", "matan"]),
        ("quadratic_solve", "Квадратное уравнение: оба корня", ["algebra", "school"]),
        ("determinant_3x3", "Определитель 3×3 разложением", ["linalg", "vtuz"]),
        ("table_squares", "Таблица квадратов: цикл по i", ["control", "school"]),
    ]
    ids = []
    for key, desc, tags in catalog_examples:
        try:
            g = EXAMPLES[key]["graph"]
            pr = probe_graph(g)
        except Exception:
            continue
        rid = corpus.write_generate(
            backing, desc, {"task_type": "static"},
            target_graph=g, probe=pr, critic=accept,
            catalog_version=catalog, engine_commit="seed", model="mock",
            approved=True, tags=tags)
        if rid:
            ids.append(rid)
    # Плюс одна repair-запись (битый граф → починенный).
    rid = corpus.write_repair(
        backing, "Ремонт: провод ссылался на несуществующий выход",
        prior_graph=graph, errors=["unknown port res on node n3"],
        target_graph=EXAMPLES["case_variant"]["graph"],
        probe=probe_graph(EXAMPLES["case_variant"]["graph"]),
        catalog_version=catalog, engine_commit="seed", model="mock",
        tags=["repair"])
    if rid:
        ids.append(rid)

    # Разметка: пара эталонов, один исключён — остальное остаётся 'auto'.
    if len(ids) >= 1:
        corpus.set_curation(ids[0], "gold", comment="чистый эталон", curator="root")
    if len(ids) >= 3:
        corpus.set_curation(ids[2], "gold", comment="хорошее разнообразие", curator="root")
    if len(ids) >= 2:
        corpus.set_curation(ids[-1], "excluded", comment="repair-дубль паттерна", curator="root")

    summary = corpus.curation_summary()
    print(f"[contour] БД: {contour_db}")
    print(f"[contour] джоб создано: {made}; корпус: {summary['total']} "
          f"(gold={summary['gold']}, excluded={summary['excluded']})")
    print(f"[contour] запускать contour_service с "
          f"CONTOUR_DB_PATH={contour_db}")


if __name__ == "__main__":
    seed_main()
    try:
        seed_contour()
    except Exception as exc:  # контур опционален — основное демо не должно падать
        print(f"[contour] пропущено ({exc.__class__.__name__}: {exc})")
    print("Готово. Демо-логины: root/admin123 (admin), alla/teach123 (teacher), "
          "s_ivanov/stud123 (student).")
