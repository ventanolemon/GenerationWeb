"""
Чистая логика offline-sync: push (идемпотентные attempts + version-check
сущностей) и pull (диф по курсору с tombstones и пагинацией).

Реализует docs/architecture/offline_sync_protocol.md. Функции не знают про
HTTP — их вызывает тонкий роутер generator_service/routers/sync.py (та же
граница, что graph_api.py ↔ routers/graph.py). Enforcement RBAC по договору
живёт в web_layer; здесь — только вычисление области видимости через
Repository.visible_subject_ids (RBAC Фаза 1) с dev-заглушкой «видно всё»
при отсутствии identity.

Три класса данных = три стратегии (§1 протокола):
  * авторский контент (Subjects/Partitions) — row_version + LWW, конфликт
    возвращает ОБЕ версии целиком (автослияние графов запрещено §2);
  * телеметрия (attempts, word_stats-дельты) — идемпотентный append по
    client_uuid / суммирование дельт, конфликтов нет по построению;
  * ресурсы (каталог узлов) — версия каталога в ответе pull, клиент сам
    решает, перезагружать ли снапшот.
"""

from __future__ import annotations
import json
import time
from typing import Any, Optional

from .repository import Repository

# Максимум строк одного типа сущности в одном ответе pull.
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 1000

_ENTITY_TABLES = {
    "subject": "Subjects",
    "partition": "Partitions",
}


# ---------- Область видимости ----------

def visible_scope(
    repo: Repository, user_id: Optional[int], role: str,
) -> Optional[list[int]]:
    """
    subject_id, видимые пользователю; None = «видно всё» (dev-заглушка,
    когда web_layer ещё не пробросил identity). Реальный RBAC уже подключён:
    с identity область считает Repository.visible_subject_ids (админ — все,
    прочие — системные + свои). Область назначений студента (партиции его
    групп) подключится сюда же, когда появятся назначения.
    """
    if user_id is None:
        return None
    return repo.visible_subject_ids(user_id, role)


# ---------- Push ----------

def push(
    repo: Repository,
    *,
    device_id: str,
    user_id: Optional[int],
    role: str = "teacher",
    attempts: Optional[list[dict]] = None,
    word_stats_deltas: Optional[list[dict]] = None,
    changed_entities: Optional[list[dict]] = None,
    user_key: Optional[str] = None,
) -> dict:
    """
    Принять пуш устройства. Порядок обработки не важен для корректности
    (телеметрия и сущности независимы), но сущности проверяются по одной:
    конфликт одной не блокирует приём остальных.
    """
    now = time.time()
    attempts = attempts or []
    word_stats_deltas = word_stats_deltas or []
    changed_entities = changed_entities or []
    stats_key = user_key or (str(user_id) if user_id is not None else device_id)

    with repo._connect() as conn:  # noqa: SLF001 — sync_api это слой данных
        _touch_device(conn, device_id, user_id, now)

        # --- Телеметрия: attempts, идемпотентно по client_uuid (§3) ---
        attempts_new = 0
        for a in attempts:
            uuid = str(a.get("client_uuid") or "").strip()
            if not uuid:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO attempts "
                "(client_uuid, user_id, partition_id, assignment_id, payload, "
                " correct, device_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid,
                    int(user_id if user_id is not None else a.get("user_id") or 0),
                    int(a.get("partition_id") or 0),
                    a.get("assignment_id"),
                    json.dumps(a.get("payload") or {}, ensure_ascii=False),
                    None if a.get("correct") is None else int(bool(a["correct"])),
                    device_id,
                    float(a.get("created_at") or now),
                ),
            )
            attempts_new += cur.rowcount
        conn.commit()

    # --- Телеметрия: дельты word_stats, сервер суммирует (§3) ---
    for d in word_stats_deltas:
        _apply_word_stat_delta(repo, stats_key, d)

    # --- Авторский контент: version-check + LWW с конфликтами (§2) ---
    accepted: list[dict] = []
    conflicts: list[dict] = []
    for change in changed_entities:
        result = _apply_entity_change(repo, change, now)
        if result.get("conflict"):
            conflicts.append(result["conflict"])
        else:
            accepted.append(result["accepted"])

    return {
        "attempts_received": len(attempts),
        "attempts_new": attempts_new,
        "accepted": accepted,
        "conflicts": conflicts,
    }


def _touch_device(conn, device_id: str, user_id: Optional[int], now: float) -> None:
    conn.execute(
        "INSERT INTO devices (device_id, user_id, last_sync_at) VALUES (?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET last_sync_at = ?, "
        "  user_id = COALESCE(excluded.user_id, devices.user_id)",
        (device_id, user_id if user_id is not None else 0, now, now),
    )


def _apply_word_stat_delta(repo: Repository, user_key: str, d: dict) -> None:
    term = str(d.get("term") or "").strip()
    if not term:
        return
    repo.ensure_word_stats_table()  # идемпотентно (CREATE IF NOT EXISTS)
    shown = int(d.get("shown") or 0)
    correct = int(d.get("correct") or 0)
    wrong = int(d.get("wrong") or 0)
    last_seen = float(d.get("last_seen") or time.time())
    with repo._connect() as conn:  # noqa: SLF001
        conn.execute(
            "INSERT INTO WordStats "
            "(user_id, term, times_shown, times_correct, times_wrong, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, term) DO UPDATE SET "
            "  times_shown = times_shown + ?, "
            "  times_correct = times_correct + ?, "
            "  times_wrong = times_wrong + ?, "
            "  last_seen = MAX(last_seen, ?)",
            (user_key, term, shown, correct, wrong, last_seen,
             shown, correct, wrong, last_seen),
        )
        conn.commit()


def _apply_entity_change(repo: Repository, change: dict, now: float) -> dict:
    """
    Одна сущность из changed_entities:
      {kind: subject|partition, id, base_version, deleted?, data{...},
       local_ref?}
    Правила §2: server.row_version == base_version → принять (row_version
    получает новое глобально-монотонное значение); иначе конфликт с ОБЕИМИ
    версиями целиком. Новая сущность (id null / не найдена) — создание,
    сервер назначает id, клиент перепривязывает по local_ref.
    """
    kind = str(change.get("kind") or "")
    table = _ENTITY_TABLES.get(kind)
    if table is None:
        return {"conflict": {
            "kind": kind, "id": change.get("id"),
            "error": f"неизвестный kind {kind!r}",
            "mine": change.get("data"), "theirs": None,
        }}
    entity_id = change.get("id")
    base_version = int(change.get("base_version") or 0)
    data = change.get("data") or {}
    local_ref = change.get("local_ref")

    with repo._connect() as conn:  # noqa: SLF001
        row = None
        if entity_id is not None:
            row = _fetch_entity(conn, kind, int(entity_id))

        if row is None:
            # Создание (офлайн-созданная сущность): сервер назначает id.
            new_id, new_version = _insert_entity(conn, repo, kind, data, now)
            conn.commit()
            return {"accepted": {
                "kind": kind, "id": new_id, "local_ref": local_ref,
                "row_version": new_version, "created": True,
            }}

        if int(row["row_version"]) != base_version:
            # Конфликт: обе версии целиком, никакого автослияния (§2).
            return {"conflict": {
                "kind": kind, "id": row["id"],
                "base_version": base_version,
                "mine": data if not change.get("deleted") else {"deleted": True},
                "theirs": row,
            }}

        ver = repo._next_row_version(conn, table)  # noqa: SLF001
        if change.get("deleted"):
            conn.execute(
                f"UPDATE {table} SET deleted_at = ?, updated_at = ?, "
                f"row_version = ? WHERE id = ?",
                (now, now, ver, row["id"]),
            )
        else:
            _update_entity(conn, kind, row["id"], data, ver, now)
        conn.commit()
        return {"accepted": {
            "kind": kind, "id": row["id"], "local_ref": local_ref,
            "row_version": ver,
            "deleted": bool(change.get("deleted")),
        }}


def _fetch_entity(conn, kind: str, entity_id: int) -> Optional[dict]:
    """Полная строка сущности, ВКЛЮЧАЯ tombstone (для честного конфликта)."""
    if kind == "subject":
        row = conn.execute(
            "SELECT id, subject_name, pra_subject, owner_user_id, "
            "       row_version, updated_at, deleted_at "
            "FROM Subjects WHERE id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "subject_name": row[1], "pra_subject": row[2],
            "owner_user_id": row[3], "row_version": row[4],
            "updated_at": row[5], "deleted_at": row[6],
        }
    row = conn.execute(
        "SELECT id, subject_id, partition_name, constracted, "
        "       generation_parametrs, row_version, updated_at, deleted_at "
        "FROM Partitions WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "subject_id": row[1], "partition_name": row[2],
        "constracted": row[3],
        "generation_parametrs": _parse_params(row[4]),
        "row_version": row[5], "updated_at": row[6], "deleted_at": row[7],
    }


def _parse_params(raw: Any) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}


def _dump_params(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False)


def _insert_entity(conn, repo: Repository, kind: str, data: dict, now: float):
    if kind == "subject":
        ver = repo._next_row_version(conn, "Subjects")  # noqa: SLF001
        cur = conn.execute(
            "INSERT INTO Subjects (subject_name, pra_subject, owner_user_id, "
            " row_version, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                str(data.get("subject_name") or ""),
                str(data.get("pra_subject") or data.get("subject_name") or ""),
                data.get("owner_user_id"),
                ver, now,
            ),
        )
        return cur.lastrowid, ver
    ver = repo._next_row_version(conn, "Partitions")  # noqa: SLF001
    cur = conn.execute(
        "INSERT INTO Partitions (subject_id, partition_name, constracted, "
        " generation_parametrs, row_version, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            int(data.get("subject_id") or 0),
            str(data.get("partition_name") or ""),
            int(data.get("constracted") or 0),
            _dump_params(data.get("generation_parametrs")),
            ver, now,
        ),
    )
    return cur.lastrowid, ver


def _update_entity(conn, kind: str, entity_id: int, data: dict,
                   ver: int, now: float) -> None:
    if kind == "subject":
        conn.execute(
            "UPDATE Subjects SET subject_name = ?, pra_subject = ?, "
            "row_version = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
            (
                str(data.get("subject_name") or ""),
                str(data.get("pra_subject") or data.get("subject_name") or ""),
                ver, now, entity_id,
            ),
        )
        return
    conn.execute(
        "UPDATE Partitions SET subject_id = ?, partition_name = ?, "
        "constracted = ?, generation_parametrs = ?, "
        "row_version = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
        (
            int(data.get("subject_id") or 0),
            str(data.get("partition_name") or ""),
            int(data.get("constracted") or 0),
            _dump_params(data.get("generation_parametrs")),
            ver, now, entity_id,
        ),
    )


# ---------- Pull ----------

def pull(
    repo: Repository,
    *,
    device_id: str,
    user_id: Optional[int],
    role: str = "teacher",
    cursors: Optional[dict] = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict:
    """
    Диф по курсорам: всё с row_version > cursor, включая tombstones,
    страницами по limit. Курсор — максимальный отданный row_version на тип
    сущности; сервер stateless по отношению к клиентам (§4). has_more по
    типу сущности — клиент повторяет pull с новыми курсорами до пустоты.

    Живые строки скоупятся областью видимости; tombstones отдаются без
    скоупа (id + версия, содержимого нет — офлайн-клиент обязан узнать об
    удалении даже если предмет выпал из его области).
    """
    cursors = cursors or {}
    limit = max(1, min(int(limit or DEFAULT_PAGE_LIMIT), MAX_PAGE_LIMIT))
    scope = visible_scope(repo, user_id, role)
    now = time.time()

    with repo._connect() as conn:  # noqa: SLF001
        _touch_device(conn, device_id, user_id, now)
        conn.commit()

        subjects, deleted_subj, cur_subj, more_subj = _pull_subjects(
            conn, int(cursors.get("subjects") or 0), limit, scope)
        partitions, deleted_part, cur_part, more_part = _pull_partitions(
            conn, int(cursors.get("partitions") or 0), limit, scope)

    # Версия каталога узлов — ресурсный снапшот (§1): клиент сравнивает со
    # своей и при расхождении перезагружает каталог. Недоступность каталога
    # не роняет sync — авторский контент и телеметрия важнее.
    try:
        from . import graph_api  # ленивый импорт: sync не тянет граф без нужды
        catalog_version = graph_api.catalog_version()
    except Exception:
        catalog_version = ""
    return {
        "subjects": subjects,
        "partitions": partitions,
        "deleted": deleted_subj + deleted_part,
        "new_cursors": {"subjects": cur_subj, "partitions": cur_part},
        "has_more": more_subj or more_part,
        "resources": {"catalog_version": catalog_version},
    }


def _pull_subjects(conn, cursor: int, limit: int, scope):
    rows = conn.execute(
        "SELECT id, subject_name, pra_subject, owner_user_id, "
        "       row_version, updated_at, deleted_at "
        "FROM Subjects WHERE row_version > ? ORDER BY row_version LIMIT ?",
        (cursor, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    alive, deleted = [], []
    new_cursor = cursor
    for r in rows:
        new_cursor = max(new_cursor, r[4])
        if r[6] is not None:
            deleted.append({"kind": "subject", "id": r[0], "row_version": r[4]})
        elif scope is None or r[0] in scope:
            alive.append({
                "id": r[0], "subject_name": r[1], "pra_subject": r[2],
                "owner_user_id": r[3], "row_version": r[4], "updated_at": r[5],
            })
    return alive, deleted, new_cursor, has_more


def _pull_partitions(conn, cursor: int, limit: int, scope):
    rows = conn.execute(
        "SELECT id, subject_id, partition_name, constracted, "
        "       generation_parametrs, row_version, updated_at, deleted_at "
        "FROM Partitions WHERE row_version > ? ORDER BY row_version LIMIT ?",
        (cursor, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    alive, deleted = [], []
    new_cursor = cursor
    for r in rows:
        new_cursor = max(new_cursor, r[5])
        if r[7] is not None:
            deleted.append({"kind": "partition", "id": r[0], "row_version": r[5]})
        elif scope is None or r[1] in scope:
            alive.append({
                "id": r[0], "subject_id": r[1], "partition_name": r[2],
                "constracted": r[3],
                "generation_parametrs": _parse_params(r[4]),
                "row_version": r[5], "updated_at": r[6],
            })
    return alive, deleted, new_cursor, has_more
