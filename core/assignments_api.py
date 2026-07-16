"""
Домашки: выдача заданий (партиций) группам + просмотр студентом.

Чистая логика (headless, как sync/analytics/admin/groups_api). Право
enforcement'а — здесь, над теми же предикатами, что RBAC:
  * teacher выдаёт задание группе, только если задачу ВИДИТ
    (visible_subject_ids: свои + системные предметы) И ведёт эту группу
    (teacher_group_ids);
  * admin — любую задачу любой группе;
  * student домашек не выдаёт (только видит свои).
Удаление выдачи — автор (assigned_by) или admin.

Роутер generator_service/routers/assignments.py адаптирует HTTP и
проверяет идентичность/роль вызывающего.
"""

from __future__ import annotations

from typing import Optional

from .repository import Repository


class AssignmentActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


def _require_partition_visible(repo, actor, role, partition_id):
    part = repo.get_partition(partition_id)
    if part is None:
        raise AssignmentActionError(f"Задание #{partition_id} не найдено.")
    if role == "admin":
        return part
    visible = repo.visible_subject_ids(actor, role)
    if part.subject_id not in visible:
        raise AssignmentActionError(
            "Нельзя выдать задание из недоступного вам предмета.")
    return part


def _require_group_taught(repo, actor, role, group_id):
    grp = repo.get_group(group_id)
    if grp is None:
        raise AssignmentActionError(f"Группа #{group_id} не найдена.")
    if role == "admin":
        return grp
    if group_id not in repo.teacher_group_ids(actor):
        raise AssignmentActionError(
            "Нельзя выдать задание группе, которую вы не ведёте.")
    return grp


def create(
    repo: Repository, *, actor_login: str, role: str,
    partition_id: int, group_id: int, due_at: Optional[float] = None,
) -> dict:
    if role not in ("teacher", "admin"):
        raise AssignmentActionError(
            "Выдавать задания могут преподаватель и администратор.")
    _require_partition_visible(repo, actor_login, role, partition_id)
    _require_group_taught(repo, actor_login, role, group_id)
    aid = repo.create_assignment(partition_id, group_id, actor_login, due_at)
    return repo.get_assignment(aid).to_dict()


def list_teaching(repo: Repository, *, actor_login: str) -> list[dict]:
    """Выдачи, сделанные этим преподавателем, со сводкой выполнения
    (member_count / solved_count — «сдали X из Y»)."""
    out = []
    for a in repo.list_assignments_for_teacher(actor_login):
        members, solved = repo.assignment_completion_counts(
            a.partition_id, a.group_id)
        d = a.to_dict()
        d["member_count"] = members
        d["solved_count"] = solved
        out.append(d)
    return out


def progress(
    repo: Repository, *, actor_login: str, role: str, assignment_id: int,
) -> dict:
    """Пофамильный прогресс по выдаче. Видит автор выдачи или admin."""
    a = repo.get_assignment(assignment_id)
    if a is None:
        raise AssignmentActionError(f"Выдача #{assignment_id} не найдена.")
    if role != "admin" and a.assigned_by != actor_login:
        raise AssignmentActionError(
            "Прогресс виден только автору выдачи.")
    return repo.assignment_progress(assignment_id)


def list_mine(repo: Repository, *, actor_login: str) -> list[dict]:
    """Домашки студента (по его группам)."""
    return [a.to_dict() for a in repo.list_assignments_for_student(actor_login)]


def delete(
    repo: Repository, *, actor_login: str, role: str, assignment_id: int,
) -> dict:
    a = repo.get_assignment(assignment_id)
    if a is None:
        raise AssignmentActionError(f"Выдача #{assignment_id} не найдена.")
    if role != "admin" and a.assigned_by != actor_login:
        raise AssignmentActionError(
            "Снять можно только собственную выдачу.")
    repo.delete_assignment(assignment_id)
    return {"deleted": assignment_id}
