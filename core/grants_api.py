"""
Выдача предметов преподавателям (docs/subject_grants.md в репозитории
Generator) — серверная половина контракта.

Админ раздаёт преподавателям доступ к предметам; преподаватель видит только
выданные. Чистая логика (headless, как sync/admin/groups/assignments_api) —
роутер generator_service/routers/grants.py адаптирует HTTP и проверяет роль
вызывающего.

Две вещи, которые здесь важнее всего:

**Умолчание разрешающее.** `default_access = "all"` означает «преподаватель
без единой выдачи видит всё»; ограничение включается по мере раздачи, а
строгий режим (`"none"`) админ включает, когда матрица заполнена. Обратный
порядок оставил бы всех преподавателей с пустым экраном в день выкатки.

**Ограничение — не про владение.** Выдача отвечает на вопрос «что мне
позволено видеть», а не «чем я владею»: выданный предмет приезжает
преподавателю и с чужим владельцем, а собственные предметы преподавателя
(`owner_user_id` = его логин) из скоупа не выпадают ни при каком наборе
выдач. Обе половины этого правила применяет `sync_api.visible_scope` — там
же обоснование.
"""

from __future__ import annotations

from typing import Optional

from .repository import Repository

DEFAULT_ACCESS_VALUES = Repository.DEFAULT_ACCESS_VALUES  # ("all", "none")


class GrantActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


# ---------- Витрина преподавателя ----------

def my_grants(repo: Repository, *, actor_login: str, role: str) -> dict:
    """
    Свои выдачи: `{scope_version, default_access, subject_ids}`.

    Для не-преподавателя (админ, студент, гость) ответ всегда «ограничения
    нет»: пустой список при `default_access: "all"`. Это не сокрытие
    настройки, а честный ответ на вопрос эндпоинта — «что применяется КО
    МНЕ»; админ по определению видит всё, студенту контент приходит
    домашками. Отдай мы ему глобальный `"none"`, клиент, применивший снимок
    без разбора роли, запер бы админа в пустой витрине. Саму настройку
    админ читает из матрицы (`admin_matrix`).
    """
    if role != "teacher":
        return {
            "scope_version": repo.scope_version(actor_login),
            "default_access": "all",
            "subject_ids": [],
        }
    return {
        "scope_version": repo.scope_version(actor_login),
        "default_access": repo.effective_default_access(actor_login),
        "subject_ids": repo.subject_grants(actor_login),
    }


def granted_scope(
    repo: Repository, login: Optional[str], role: str,
) -> Optional[set[int]]:
    """
    Чем выдачи ограничивают скоуп пользователя; None — ничем.

    Ограничение действует только для роли `teacher` и только когда снимок
    что-то ограничивает: строгий режим (`"none"`) — всегда, мягкий — как
    только выдан хотя бы один предмет (тогда набор становится
    исчерпывающим). Это ровно та же таблица истинности, что у
    `GrantsSnapshot.restricts` на десктопе: обе половины контракта обязаны
    отвечать одинаково, иначе витрина и скоуп pull'а разъедутся.
    """
    if role != "teacher" or not login:
        return None
    ids = set(repo.subject_grants(login))
    if repo.effective_default_access(login) == "none" or ids:
        return ids
    return None


# ---------- Матрица администратора ----------

def admin_matrix(repo: Repository, *,
                 organization_id: Optional[int] = None) -> dict:
    """
    Данные админской вкладки одним вызовом: режим умолчания, преподаватели,
    предметы, текущие выдачи. Один вызов, а не три, потому что матрица без
    любой из частей не рисуется — экономить нечего, а гонять клиента по
    трём эндпоинтам значит показать ему несогласованный срез.

    `organization_id` сужает матрицу до своей организации: выдачи работают
    внутри неё (§8.1), и показывать админу кафедры преподавателей чужой —
    значит предлагать ему операцию, которая всё равно будет отвергнута.
    """
    teachers = [
        {"login": u.login, "fio": u.fio}
        for u in repo.list_users()
        if u.role == "teacher"
        and (organization_id is None
             or repo.user_organization_id(u.login) == organization_id)
    ]
    subjects = [
        {"id": s.id, "subject_name": s.name,
         "is_builtin": repo.subject_owner(s.id) is None}
        for s in repo.list_subjects()
        if organization_id is None
        or repo.subject_organization_id(s.id) in (None, organization_id)
    ]
    grants = repo.all_subject_grants()
    # Преподаватель без выдач обязан присутствовать пустым списком: иначе
    # клиент не отличит «ничего не выдано» от «строка ещё не загружена».
    for t in teachers:
        grants.setdefault(t["login"], [])
    default_access = (repo.get_organization(organization_id) or {}).get(
        "default_subject_access") if organization_id else None
    return {
        "default_access": default_access or repo.default_subject_access(),
        "teachers": teachers,
        "subjects": subjects,
        "grants": grants,
    }


def set_teacher_grants(
    repo: Repository, *, actor_login: str, target_login: str, subject_ids,
) -> dict:
    """
    Заменить выдачи преподавателя целиком. Возвращает `{ok, scope_version}`.

    Проверяем и цель, и содержимое: выдача несуществующего предмета — тихо
    мёртвая строка, которую потом никто не найдёт, а выдача не-преподавателю
    — заявка на то, что роль и права разъедутся при следующей смене роли.
    """
    prof = repo.get_user_profile(target_login)
    if prof is None:
        raise GrantActionError(f"Пользователь {target_login!r} не найден.")
    if prof.role != "teacher":
        raise GrantActionError(
            f"Выдачи предметов касаются только преподавателей; у "
            f"{target_login!r} роль {prof.role!r}.")

    try:
        ids = sorted({int(s) for s in subject_ids})
    except (TypeError, ValueError) as exc:
        raise GrantActionError("subject_ids: ожидается список целых id.") from exc

    known = {s.id for s in repo.list_subjects()}
    unknown = [s for s in ids if s not in known]
    if unknown:
        raise GrantActionError(
            f"Неизвестные предметы: {', '.join(str(s) for s in unknown)}.")

    version = repo.replace_subject_grants(target_login, ids,
                                          granted_by=actor_login)
    return {"ok": True, "login": target_login, "subject_ids": ids,
            "scope_version": version}


def set_default_access(repo: Repository, *, default_access: str) -> dict:
    """Переключить режим умолчания. Инкрементирует эпоху всем преподавателям
    — переключение меняет видимый набор у каждого, у кого нет явных выдач."""
    if default_access not in DEFAULT_ACCESS_VALUES:
        raise GrantActionError(
            f"default_access: 'all'|'none', не {default_access!r}.")
    repo.set_default_subject_access(default_access)
    return {"ok": True, "default_access": default_access}
