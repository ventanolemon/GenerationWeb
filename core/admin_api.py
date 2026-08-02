"""
Администрирование пользователей: список + смена роли (admin-only).

Чистая логика (headless, как sync_api/analytics_api) — роутер
generator_service/routers/admin.py только адаптирует HTTP и проверяет, что
вызывающий admin (роль из X-User-Role, server-authoritative — см.
docs/ui_rework_plan.md «Роли: редактирование — server-authoritative,
admin-only»). Здесь — только доменные гарантии, не зависящие от транспорта:
без self-elevation/self-demotion и без понижения последнего администратора
(иначе система осталась бы без единого admin).
"""

from __future__ import annotations

from .repository import ROLES, Repository


class AdminActionError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400
    (в отличие от 401/403, которые про identity/роль вызывающего)."""


def list_users(repo: Repository) -> list[dict]:
    return [u.to_dict() for u in repo.list_users()]


def change_role(
    repo: Repository, *, actor_login: str, target_login: str, new_role: str,
) -> dict:
    if new_role not in ROLES:
        raise AdminActionError(
            f"Неизвестная роль {new_role!r}; допустимы {ROLES}.")
    if target_login == actor_login:
        raise AdminActionError("Нельзя изменить собственную роль.")

    # Проверка и запись — ОДНОЙ транзакцией. «Нельзя понизить последнего
    # администратора» — это классическое check-then-act: два одновременных
    # понижения двух последних админов оба видели бы count == 2, оба
    # проходили бы проверку, и система осталась бы без единого админа.
    # Раньше проверка шла в своём соединении, а запись — вообще вне его.
    with repo.transaction() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE login = ?", (target_login,)
        ).fetchone()
        if row is None:
            raise AdminActionError(f"Пользователь {target_login!r} не найден.")
        current_role = row[0]
        if current_role == "admin" and new_role != "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]
            if admin_count <= 1:
                raise AdminActionError(
                    "Нельзя понизить последнего администратора.")

        repo.set_user_role(target_login, new_role)
        # Роль меняет видимый набор предметов (выдачи касаются только
        # преподавателей, а RBAC-область у admin/teacher/student разная),
        # поэтому смена роли — такое же событие scope-эпохи, как выдача и
        # отзыв: docs/subject_grants.md. Без инкремента десктоп разжалованного
        # преподавателя продолжил бы жить с прежним набором до первой правки
        # контента.
        repo.bump_scope_version(target_login)
    return {"login": target_login, "role": new_role}
