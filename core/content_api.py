"""
Хранилища контента: личное преподавателя ↔ общее, и перенос между ними.

Развитие уже существующего механизма, а не новая сущность.
`Subjects.owner_user_id` и есть «где лежит предмет»:

  * `NULL`  — ОБЩЕЕ хранилище: предмет принадлежит продукту, виден всем
    (с поправкой на выдачи), правят его администраторы;
  * `логин` — ЛИЧНОЕ хранилище преподавателя: виден и правится владельцем,
    наружу через публичный API не уходит.

Отсюда всё остальное следует само. Преподаватель, отправивший предмет с
десктопа (`/sync/push`), автоматически кладёт его в своё личное: владельца
назначает сервер по автору запроса, и подменить его клиент не может
(`sync_api._insert_entity`). Админ переносит предмет между хранилищами этой
же одной ручкой — меняя владельца.

Партиции переезжают вместе с предметом сами: своего владельца у них нет,
права выводятся из предмета (rbac_and_data_model.md §3).

Чистая логика (headless, как grants/admin/sync_api) — роутер
`generator_service/routers/admin_content.py` адаптирует HTTP.
"""

from __future__ import annotations

from typing import Optional

from . import api_clients
from .repository import Repository

# Куда можно положить предмет, кроме личного хранилища конкретного человека.
SHARED = None


class ContentActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


def storage_of(owner: Optional[str]) -> str:
    return "shared" if owner is None else "personal"


# ---------- Обзор ----------

def overview(repo: Repository, *,
             organization_id: Optional[int] = None) -> dict:
    """
    Что где лежит — данные админского экрана переносов.

    `organization_id=None` — весь обзор (администратор развёртывания);
    иначе только своя организация плюс встроенные предметы: они
    принадлежат продукту и видны всем (§8.1), и прятать их от админа
    организации значило бы показывать ему неполную картину его же
    каталога.
    """
    subjects = repo.subjects_with_owner()
    if organization_id is not None:
        subjects = [s for s in subjects
                    if s.get("organization_id") in (organization_id, None)]
    for s in subjects:
        s["storage"] = storage_of(s["owner"])
    return {
        "subjects": subjects,
        "shared_count": sum(1 for s in subjects if s["owner"] is None),
        "personal_count": sum(1 for s in subjects if s["owner"] is not None),
    }


def list_mine(repo: Repository, *, actor_login: str) -> dict:
    """Личное хранилище преподавателя: что он создал сам (в т.ч. приехавшее
    с его десктопа)."""
    subjects = [s for s in repo.subjects_with_owner()
                if s["owner"] == actor_login]
    for s in subjects:
        s["storage"] = "personal"
    return {"subjects": subjects}


# ---------- Перенос ----------

def _affected_logins(repo: Repository, old: Optional[str],
                     new: Optional[str]) -> set[str]:
    """
    Чьи эпохи скоупа надо поднять после переезда.

    Это не формальность: без инкремента изменение до десктопов НЕ ДОЕДЕТ в
    одну из сторон. Курсорный диф принесёт новую версию строки тому, у кого
    предмет остался в области видимости, но у того, КТО ЕГО ПОТЕРЯЛ, версия
    не изменится в его пользу — область считается на сервере, а не в дифе
    (docs/subject_grants.md, «scope-эпоха»).

    Если в переезде участвует общее хранилище, затронуты все преподаватели
    сразу: общее видно всем (у кого нет явных выдач), значит и появление, и
    исчезновение из него меняет набор у каждого. Личное → личное затрагивает
    ровно двоих.
    """
    if old is None or new is None:
        return {u.login for u in repo.list_users() if u.role == "teacher"}
    return {old, new}


def _require_owner_exists(repo: Repository, login: Optional[str],
                          organization_id: Optional[int] = None) -> None:
    """
    Кому вообще можно отдать личное хранилище.

    С появлением организаций к роли добавилась принадлежность: передать
    предмет преподавателю ЧУЖОЙ организации значило бы протащить контент
    через границу контейнера, которую §8.1 объявляет непроницаемой.
    `organization_id=None` — проверку организации не делаем (администратор
    развёртывания переносит куда угодно осознанно).
    """
    if login is None:
        return
    profile = repo.get_user_profile(login)
    if profile is None:
        raise ContentActionError(f"Пользователь {login!r} не найден.")
    if profile.role not in ("teacher", "admin"):
        raise ContentActionError(
            f"Личное хранилище есть у преподавателя и администратора; "
            f"у {login!r} роль {profile.role!r}.")
    if organization_id is not None:
        target_org = repo.user_organization_id(login)
        if target_org != organization_id:
            raise ContentActionError(
                f"{login!r} состоит в другой организации; передавать "
                f"контент через границу организации нельзя.")


def transfer(repo: Repository, *, subject_id: int,
             new_owner: Optional[str], actor_login: str) -> dict:
    """
    Перенести предмет: `new_owner=None` — в общее, логин — в личное.

    Одной транзакцией со всеми последствиями: сменой владельца, инкрементом
    эпох затронутых пользователей и отзывом публичного доступа (см. ниже).
    Порознь они оставляли бы окно, в котором предмет уже личный, а публичный
    ключ его ещё отдаёт.
    """
    with repo.transaction():
        current = repo.subjects_with_owner()
        subject = next((s for s in current if s["id"] == subject_id), None)
        if subject is None:
            raise ContentActionError(f"Предмет #{subject_id} не найден.")
        old_owner = subject["owner"]
        if old_owner == new_owner:
            raise ContentActionError(
                f"Предмет уже в {'общем' if new_owner is None else 'личном'} "
                f"хранилище — переносить нечего.")
        _require_owner_exists(repo, new_owner)

        repo.set_subject_owner(subject_id, new_owner)

        # Уход в личное = контент перестал принадлежать продукту. Публичный
        # API отдаёт наружу только общее либо явно выданное (public_api.md
        # §8), и оставить выдачу ключу значило бы раздавать наружу личное
        # преподавателя без отдельного решения. Возврат в общее выдачу НЕ
        # восстанавливает — она была решением, а не свойством предмета.
        revoked_from = []
        if new_owner is not None:
            for client in repo.list_api_clients():
                granted = repo.api_client_subject_ids(client["id"])
                if subject_id in granted:
                    repo.replace_api_client_subjects(
                        client["id"], [s for s in granted if s != subject_id])
                    revoked_from.append(client["name"])

        for login in _affected_logins(repo, old_owner, new_owner):
            repo.bump_scope_version(login)

    return {
        "ok": True,
        "subject_id": subject_id,
        "name": subject["name"],
        "from": storage_of(old_owner),
        "to": storage_of(new_owner),
        "owner": new_owner,
        "moved_by": actor_login,
        "api_access_revoked_from": revoked_from,
    }


def publish(repo: Repository, *, subject_id: int, actor_login: str) -> dict:
    """Личное → общее. Именованная обёртка: в интерфейсе это отдельная
    кнопка, и читать `publish` понятнее, чем `transfer(new_owner=None)`."""
    return transfer(repo, subject_id=subject_id, new_owner=SHARED,
                    actor_login=actor_login)


def assign_to(repo: Repository, *, subject_id: int, login: str,
              actor_login: str) -> dict:
    """Общее → личное указанного преподавателя (или передача между личными)."""
    return transfer(repo, subject_id=subject_id, new_owner=login,
                    actor_login=actor_login)


# ---------- Что увидит публичный API после переноса ----------

def public_visibility(repo: Repository, subject_id: int) -> dict:
    """
    Диагностика для админского экрана: кому предмет доступен наружу.

    Нужна ровно потому, что связей две и они неочевидны вместе: общее
    хранилище отдаётся всем ключам БЕЗ явных выдач, а ключ С выдачами видит
    только выданное. Показать это одним ответом дешевле, чем объяснять.
    """
    owner = repo.subject_owner(subject_id)
    clients = []
    for client in repo.list_api_clients():
        ids = api_clients.client_subject_ids(repo, client["id"])
        if subject_id in ids:
            clients.append({"id": client["id"], "name": client["name"],
                            "explicit": bool(repo.api_client_subject_ids(
                                client["id"]))})
    return {"subject_id": subject_id, "storage": storage_of(owner),
            "clients": clients}
