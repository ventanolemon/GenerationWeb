"""
Предметы: завести, переименовать, удалить (headless).

До этого модуля предмет НЕЛЬЗЯ БЫЛО СОЗДАТЬ через продукт вовсе:
`create_subject`/`ensure_subject` не вызывались ни одним роутером, и
предметы появлялись только из `bootstrap` при старте сервиса. Это дыра, а
не «утраченная возможность»: преподаватель, которому нужен свой предмет,
не мог его завести никак.

Заодно чинится утечка витрины. `GET /subjects` отдавал ВСЕ предметы без
скоупа — после §8 это означало, что преподаватель одной организации видит
в выпадающем списке предметы соседней. Скоуп здесь тот же, что у синка и
аналитики (`content_authz.visible_scope`), и это принципиально: два
разных ответа на вопрос «что мне видно» разъезжаются, как разъехались
четырнадцать копий гейта роли.

Правила
-------
* **завести** — teacher и admin; предмет заводится СВОИМ (владелец —
  автор) и в его организации. Встроенный предмет (владелец `NULL`) так не
  создаётся: это решение уровня развёртывания, для него есть
  `content_api.publish`;
* **переименовать / удалить** — владелец, либо admin своей организации,
  либо администратор развёртывания;
* **удалить** — мягко (`deleted_at`) и только ПУСТОЙ. Каскадом сносить
  разделы значило бы уничтожать чужую работу одним нажатием; здесь
  отказ с указанием, сколько разделов мешает.
"""

from __future__ import annotations

import time
from typing import Optional

from . import content_authz
from .repository import Repository


class SubjectActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


WRITE_ROLES = content_authz.WRITE_ROLES


def _require_subject(repo: Repository, subject_id: int) -> dict:
    for row in repo.subjects_with_owner():
        if row["id"] == subject_id:
            return row
    raise SubjectActionError(f"Предмет #{subject_id} не найден.")


def _require_can_edit(repo: Repository, row: dict, actor: str, role: str,
                      organization_id: Optional[int]) -> None:
    """
    Кто вправе править предмет.

    Встроенный (владельца нет) правит только администратор развёртывания:
    он виден всем организациям сразу, и переименовать его из одной
    кафедры значило бы поменять надпись у всех.
    """
    if repo.is_superuser(actor):
        return
    if row["owner"] is None:
        raise SubjectActionError(
            "Встроенный предмет принадлежит продукту; менять его может "
            "только администратор развёртывания.")
    if row["owner"] == actor:
        return
    if role == "admin" and row.get("organization_id") == organization_id:
        return
    raise SubjectActionError(
        f"Предмет «{row['name']}» принадлежит другому владельцу.")


# ---------- Чтение ----------

def visible(repo: Repository, *, actor: Optional[str], role: str) -> dict:
    """
    Предметы, видимые актору, — та же область, что у синка.

    Гость (`actor is None`) видит встроенные: без них ему не с чем
    работать вовсе, а авторского контента у него и так нет.
    """
    subjects = repo.subjects_with_owner()
    if actor is None:
        rows = [s for s in subjects if s["owner"] is None]
    else:
        scope = content_authz.visible_scope(repo, actor, role)
        rows = (subjects if scope is None
                else [s for s in subjects if s["id"] in set(scope)])
    for row in rows:
        row["is_builtin"] = row["owner"] is None
        row["is_mine"] = row["owner"] == actor
    return {"subjects": rows}


# ---------- Запись ----------

def create(repo: Repository, *, name: str, parent_name: str = "",
           actor: str, role: str,
           organization_id: Optional[int] = None) -> dict:
    """Завести предмет в личном хранилище автора."""
    clean = (name or "").strip()
    if not clean:
        raise SubjectActionError("У предмета должно быть название.")
    if role not in WRITE_ROLES:
        raise SubjectActionError(
            f"Роль {role!r} не заводит предметы — только teacher и admin.")
    # Тёзка в пределах ВИДИМОГО набора: одноимённые предметы у разных
    # владельцев допустимы (у каждого свой), но два своих с одним именем
    # автор не различит в выпадающем списке.
    for row in repo.subjects_with_owner():
        if row["name"] == clean and row["owner"] == actor:
            raise SubjectActionError(f"У вас уже есть предмет «{clean}».")

    subject_id = repo.create_subject(clean, (parent_name or clean).strip(),
                                     owner_user_id=actor)
    if organization_id is None:
        organization_id = repo.user_organization_id(actor)
    repo.set_subject_organization(subject_id, organization_id)
    # Появление предмета меняет видимый набор автора — десктоп обязан
    # узнать о нём при следующем синке, а не после первой правки.
    repo.bump_scope_version(actor)
    return _require_subject(repo, subject_id)


def rename(repo: Repository, *, subject_id: int, name: str, actor: str,
           role: str, organization_id: Optional[int] = None) -> dict:
    clean = (name or "").strip()
    if not clean:
        raise SubjectActionError("У предмета должно быть название.")
    row = _require_subject(repo, subject_id)
    _require_can_edit(repo, row, actor, role, organization_id)
    repo.rename_subject(subject_id, clean)
    return _require_subject(repo, subject_id)


def delete(repo: Repository, *, subject_id: int, actor: str, role: str,
           organization_id: Optional[int] = None) -> dict:
    """
    Мягкое удаление и только пустого предмета.

    Каскад здесь был бы опасен несоразмерно выигрышу: один клик сносит все
    разделы, включая приехавшие с чужого десктопа. Поэтому отказ с числом
    мешающих разделов — человек сам решит, перенести их или удалить.
    """
    row = _require_subject(repo, subject_id)
    _require_can_edit(repo, row, actor, role, organization_id)
    count = len(repo.list_partitions_for_subject(subject_id))
    if count:
        raise SubjectActionError(
            f"В предмете «{row['name']}» ещё {count} "
            f"{'раздел' if count == 1 else 'раздела/разделов'}; "
            f"перенесите или удалите их сначала.")
    repo.delete_subject(subject_id)
    if row["owner"]:
        repo.bump_scope_version(row["owner"])
    return {"id": subject_id, "deleted": True}


__all__ = ["SubjectActionError", "visible", "create", "rename", "delete"]
