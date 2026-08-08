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

from . import content_authz
from .repository import Repository

# Максимум строк одного типа сущности в одном ответе pull.
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 1000

# Предел страницы в режиме пересборки скоупа — фактически «без предела»,
# см. обоснование в pull().
_RESYNC_NO_LIMIT = 1_000_000_000

_ENTITY_TABLES = {
    "subject": "Subjects",
    "partition": "Partitions",
}


# ---------- Область видимости ----------

# Область видимости живёт в `core/content_authz.py` — она такое же правило
# доступа, как и проверка права на запись, и нужна не только синку: витрину
# авторского содержимого разделов (`GET /partitions/{id}`) обязан ограничивать
# тот же скоуп. Здесь оставлено имя, потому что снаружи её знают как
# `sync_api.visible_scope`.
visible_scope = content_authz.visible_scope


# ---------- Push ----------

def push(
    repo: Repository,
    *,
    device_id: str,
    user_id: Optional[str],
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

    Права на запись проверяются у КАЖДОЙ сущности
    (`_authorize_entity_change`), и граница проходит по классу данных, а не
    по эндпоинту: телеметрию шлёт кто угодно, включая гостя без логина, —
    её и порождает решающий задачи; авторский контент правит только
    опознанный teacher/admin и только не-чужой. Отказ приезжает конфликтом
    с `forbidden: true`, а не молчанием.
    """
    now = time.time()
    attempts = attempts or []
    word_stats_deltas = word_stats_deltas or []
    changed_entities = changed_entities or []
    stats_key = user_key or (user_id if user_id is not None else device_id)

    with repo.transaction() as conn:
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
                    # user_id — логин-строка (X-User-Id); NOT NULL, поэтому для
                    # анонима/гостя фолбэк на переданный в attempt или пусто.
                    str(user_id if user_id is not None
                        else a.get("user_id") or ""),
                    int(a.get("partition_id") or 0),
                    a.get("assignment_id"),
                    json.dumps(a.get("payload") or {}, ensure_ascii=False),
                    None if a.get("correct") is None else int(bool(a["correct"])),
                    device_id,
                    float(a.get("created_at") or now),
                ),
            )
            attempts_new += cur.rowcount

    # --- Телеметрия: дельты word_stats, сервер суммирует (§3) ---
    for d in word_stats_deltas:
        _apply_word_stat_delta(repo, stats_key, d)

    # --- Авторский контент: version-check + LWW с конфликтами (§2) ---
    accepted: list[dict] = []
    conflicts: list[dict] = []
    for change in changed_entities:
        result = _apply_entity_change(repo, change, now, user_id, role)
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


def _touch_device(conn, device_id: str, user_id: Optional[str], now: float) -> None:
    conn.execute(
        "INSERT INTO devices (device_id, user_id, last_sync_at) VALUES (?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET last_sync_at = ?, "
        "  user_id = COALESCE(excluded.user_id, devices.user_id)",
        (device_id, user_id if user_id is not None else "", now, now),
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
    with repo.transaction() as conn:
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


def _authorize_entity_change(
    repo: Repository, kind: str, row: Optional[dict], data: dict,
    actor: Optional[str], role: str,
) -> Optional[str]:
    """
    Вправе ли актор писать эту сущность. None — вправе; строка — причина
    отказа (уедет клиенту конфликтом, см. `_apply_entity_change`).

    Само правило живёт в `core/content_authz.py` — общее с CRUD по HTTP
    (`POST/DELETE /partitions`). Держать его здесь было бы удобнее ровно до
    того момента, когда у таблицы появился второй вход на запись: он
    появился, правило при нём не повторили, и получилась дыра. Теперь
    источник один, а здесь только перевод в форму синка — тому нужен текст
    для конверта конфликта, а не HTTP-статус.
    """
    refusal = content_authz.check_entity_change(repo, kind, row, data,
                                                actor, role)
    return refusal[1] if refusal else None


def _missing_packages(repo: Repository, kind: str, change: dict,
                      data: dict, actor: Optional[str]) -> Optional[dict]:
    """
    Отвергнуть граф, для которого на сервере нет нужного пакета узлов.

    Проверка стоит здесь, на приёме, а НЕ при генерации — и это главное
    решение всей затеи с пакетами. Приняв такой граф, сервер сложил бы себе
    мину: она сработает у каждого, кто его откроет, и у стороннего
    интегратора через публичный API, причём в виде «не удалось
    сгенерировать» без единого намёка на причину. Отказ на входе называет
    причину и кладёт запрос администратору.

    Тихо пропускаем, когда пакетов не заведено вовсе: до появления первого
    пакета механизм не должен менять поведение синка ни на йоту.
    """
    if kind != "partition" or change.get("deleted"):
        return None
    params = data.get("generation_parametrs")
    if isinstance(params, str):
        params = _parse_params(params)
    try:
        from . import node_packages
        from .graph.nodes import DEFAULT_REGISTRY
        node_packages.check_graph_requirements(
            repo, params, DEFAULT_REGISTRY.type_ids(), requested_by=actor or "")
    except ImportError:                              # pragma: no cover
        return None                                  # движок графов не собран
    except Exception as exc:
        if type(exc).__name__ != "MissingPackages":
            raise
        return {"conflict": {
            "kind": kind, "id": change.get("id"),
            "error": str(exc), "missing_packages": list(exc.packages),
            "unknown_node_types": list(exc.unknown_types),
            "mine": data, "theirs": None,
        }}
    return None


def _apply_entity_change(
    repo: Repository, change: dict, now: float,
    actor: Optional[str] = None, role: str = "teacher",
) -> dict:
    """
    Одна сущность из changed_entities:
      {kind: subject|partition, id, base_version, deleted?, data{...},
       local_ref?}
    Правила §2: server.row_version == base_version → принять (row_version
    получает новое глобально-монотонное значение); иначе конфликт с ОБЕИМИ
    версиями целиком. Новая сущность (id null / не найдена) — создание,
    сервер назначает id, клиент перепривязывает по local_ref.

    Отказ по правам возвращается ТЕМ ЖЕ конфликтом с полем `error` (плюс
    `forbidden: true`), что и неизвестный kind: контракт с клиентом от этого
    не меняется — он уже складывает такие ответы в стэш конфликтов, где их
    видно человеку. Молча проглотить отказ нельзя: правка осталась бы на
    устройстве, а пользователь считал бы её уехавшей.
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

    with repo.transaction() as conn:
        row = None
        if entity_id is not None:
            row = _fetch_entity(conn, kind, int(entity_id))

        denial = _authorize_entity_change(repo, kind, row, data, actor, role)
        if denial is not None:
            return {"conflict": {
                "kind": kind, "id": change.get("id"),
                "error": denial, "forbidden": True,
                "mine": data if not change.get("deleted") else {"deleted": True},
                "theirs": row,
            }}

        missing = _missing_packages(repo, kind, change, data, actor)
        if missing is not None:
            return missing

        if row is None:
            # Создание (офлайн-созданная сущность): сервер назначает id.
            new_id, new_version = _insert_entity(conn, repo, kind, data, now,
                                                 actor, role)
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

        ver = repo.next_row_version(conn, table)
        if change.get("deleted"):
            conn.execute(
                f"UPDATE {table} SET deleted_at = ?, updated_at = ?, "
                f"row_version = ? WHERE id = ?",
                (now, now, ver, row["id"]),
            )
        else:
            _update_entity(conn, kind, row["id"], data, ver, now)
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


def _insert_entity(conn, repo: Repository, kind: str, data: dict, now: float,
                   actor: Optional[str] = None, role: str = "teacher"):
    if kind == "subject":
        ver = repo.next_row_version(conn, "Subjects")
        # Владельца назначает СЕРВЕР, а не клиент. Присланный owner_user_id
        # — это заявка, а не факт: устройство могло объявить предмет чужим
        # (подставить владельцем другого) или системным (owner NULL —
        # такие видят все, а правят одни админы). Полю с той стороны
        # доверять нечему, поэтому владельцем становится автор запроса.
        #
        # Админу поле оставлено, но РАСЩЕПЛЕНО (§8.1): одна строка кода
        # делала два разных дела. «Отдать другому логину» — операция внутри
        # организации, её вправе админ организации. «Сделать встроенным»
        # (owner = NULL) — заведение предмета, видимого ВСЕМ организациям,
        # то есть решение уровня продукта: только администратор
        # развёртывания. Иначе админ любой кафедры раздавал бы контент
        # всему развёртыванию одним push'ем с десктопа.
        owner = actor
        if role == "admin":
            claimed = data.get("owner_user_id")
            if claimed is None:
                owner = None if repo.is_superuser(actor or "") else actor
            else:
                owner = claimed
        # Организация предмета — организация владельца. У встроенного
        # (owner IS NULL) её нет: он принадлежит продукту и виден всем.
        org_id = (repo.user_organization_id(owner)
                  if owner is not None else None)
        cur = conn.execute(
            "INSERT INTO Subjects (subject_name, pra_subject, owner_user_id, "
            " organization_id, row_version, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(data.get("subject_name") or ""),
                str(data.get("pra_subject") or data.get("subject_name") or ""),
                owner, org_id,
                ver, now,
            ),
        )
        return cur.lastrowid, ver
    ver = repo.next_row_version(conn, "Partitions")
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
    user_id: Optional[str],
    role: str = "teacher",
    cursors: Optional[dict] = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    scope_version: Optional[int] = None,
) -> dict:
    """
    Диф по курсорам: всё с row_version > cursor, включая tombstones,
    страницами по limit. Курсор — максимальный отданный row_version на тип
    сущности; сервер stateless по отношению к клиентам (§4). has_more по
    типу сущности — клиент повторяет pull с новыми курсорами до пустоты.

    Живые строки скоупятся областью видимости; tombstones отдаются без
    скоупа (id + версия, содержимого нет — офлайн-клиент обязан узнать об
    удалении даже если предмет выпал из его области).

    **Scope-эпоха** (docs/subject_grants.md). Диф по row_version не переносит
    изменение ПРАВ: выдали предмет — его версия старая, курсор клиента её
    давно прошёл, предмет не приедет никогда; отозвали — версия не менялась
    вовсе, события нет. Поэтому клиент присылает известную ему эпоху
    (`scope_version`), а сервер при расхождении объявляет пересборку: курсоры
    игнорируются, набор идёт с нуля, ответ помечен `resync: true`. Клиент
    применяет страницы как обычно и по завершении удаляет у себя то, чего в
    наборе не было.

    Пересборка отдаётся ОДНИМ ответом, без пагинации, и это не оптимизация,
    а условие корректности. Клиент в режиме пересборки шлёт пустые курсоры на
    каждой странице (иначе он потерял бы «с нуля»), а сервер по отношению к
    клиентам stateless и вторую страницу от первой не отличает — разбитая на
    страницы пересборка не сошлась бы. Ограничить её вместо этого обрезанием
    набора нельзя: клиент удаляет всё, что не приехало, и обрезанная страница
    означала бы удаление законно выданного контента. Набор ограничен областью
    видимости одного пользователя, а сама пересборка происходит только при
    изменении его прав — цена приемлемая.

    Пересборка возможна только для опознанного пользователя: без identity
    скоуп и так «видно всё», и объявлять клиенту чистку было бы вредно.
    """
    cursors = cursors or {}
    limit = max(1, min(int(limit or DEFAULT_PAGE_LIMIT), MAX_PAGE_LIMIT))
    server_scope = repo.scope_version(user_id)
    resync = user_id is not None and int(scope_version or 0) != server_scope
    if resync:
        cursors = {}
        limit = _RESYNC_NO_LIMIT
    scope = visible_scope(repo, user_id, role)
    now = time.time()

    with repo.transaction() as conn:
        _touch_device(conn, device_id, user_id, now)

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
    out = {
        "subjects": subjects,
        "partitions": partitions,
        "deleted": deleted_subj + deleted_part,
        "new_cursors": {"subjects": cur_subj, "partitions": cur_part},
        "has_more": more_subj or more_part,
        "resources": {"catalog_version": catalog_version},
        # Эпоха отдаётся всегда: клиент сохраняет её ПОСЛЕ успешной чистки,
        # и без неё он не смог бы закрыть пересборку.
        "scope_version": server_scope,
    }
    if resync:
        out["resync"] = True
    return out


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
