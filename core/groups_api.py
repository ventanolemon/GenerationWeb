"""
Группы и назначение преподавателей (admin-управление + teacher read-view).

Чистая логика (headless, как sync_api/analytics_api/admin_api) — роутер
generator_service/routers/groups.py адаптирует HTTP и проверяет роль
вызывающего. Здесь — доменные гарантии, не зависящие от транспорта:
существование группы/пользователя, роль назначаемого преподавателя
(teacher/admin), непустое уникальное имя.

Модель: структурная группа (`groups`+`group_members`) — источник истины
членства; преподаватель привязывается к группам через `teacher_groups`.
Свободный `users."group"` (метка курса из регистрации) синхронизируется с
членством в Repository.create_user и seed'ом миграции 003.
"""

from __future__ import annotations

from .repository import Repository


class GroupActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


def _group_dict(repo: Repository, group) -> dict:
    d = group.to_dict()
    members = repo.list_group_members(group.id)
    teachers = repo.group_teachers(group.id)
    d["members"] = members
    d["teachers"] = teachers
    d["member_count"] = len(members)
    return d


def list_groups(repo: Repository) -> list[dict]:
    return [_group_dict(repo, g) for g in repo.list_groups()]


def create_group(repo: Repository, *, name: str, actor_login: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise GroupActionError("Имя группы не может быть пустым.")
    if repo.group_by_name(name) is not None:
        raise GroupActionError(f"Группа {name!r} уже существует.")
    gid = repo.create_group(name, created_by=actor_login)
    return _group_dict(repo, repo.get_group(gid))


def _require_group(repo: Repository, group_id: int):
    grp = repo.get_group(group_id)
    if grp is None:
        raise GroupActionError(f"Группа #{group_id} не найдена.")
    return grp


def _require_user(repo: Repository, login: str):
    prof = repo.get_user_profile(login)
    if prof is None:
        raise GroupActionError(f"Пользователь {login!r} не найден.")
    return prof


def add_member(repo: Repository, *, group_id: int, login: str) -> dict:
    grp = _require_group(repo, group_id)
    _require_user(repo, login)
    repo.add_group_member(group_id, login)
    return _group_dict(repo, grp)


def remove_member(repo: Repository, *, group_id: int, login: str) -> dict:
    grp = _require_group(repo, group_id)
    repo.remove_group_member(group_id, login)
    return _group_dict(repo, grp)


def assign_teacher(repo: Repository, *, group_id: int, login: str) -> dict:
    grp = _require_group(repo, group_id)
    prof = _require_user(repo, login)
    if prof.role not in ("teacher", "admin"):
        raise GroupActionError(
            f"Назначать на группу можно только teacher/admin; у {login!r} "
            f"роль {prof.role!r}.")
    repo.assign_teacher_to_group(login, group_id)
    return _group_dict(repo, grp)


def unassign_teacher(repo: Repository, *, group_id: int, login: str) -> dict:
    grp = _require_group(repo, group_id)
    repo.unassign_teacher_from_group(login, group_id)
    return _group_dict(repo, grp)


def teacher_groups(repo: Repository, *, teacher_login: str) -> list[dict]:
    """Группы, назначенные преподавателю (read-view для /groups/mine)."""
    out = []
    for gid in repo.teacher_group_ids(teacher_login):
        grp = repo.get_group(gid)
        if grp is not None:
            out.append(_group_dict(repo, grp))
    return out
