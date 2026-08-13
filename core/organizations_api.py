"""
Организации: смысл и инварианты (§8 плана).

Организация — **контейнер, а не третий фильтр**. Ограничений видимости и
так было два (`owner_user_id` — личное/общее, `subject_grants` — выдачи), и
третий поверх сделал бы хуже. Поэтому люди, группы и предметы принадлежат
организации, а выдачи работают ВНУТРИ неё: чужой организации не видно
вовсе, по построению.

Единственное, что пересекает границу, — **встроенные предметы**
(`owner_user_id IS NULL`, `organization_id IS NULL`): они принадлежат
продукту и видны всем.

**Два разных администратора.** С появлением организаций `admin` означает
«админ своей организации». Решения уровня развёртывания — какие пакеты
узлов установлены, ключи подписи, выпуски приложения, публичный API —
остаются у администратора развёртывания (`users.is_superuser`). Это не
«админ плюс уровень», а другая ось: набор установленных пакетов один на
развёртывание, иначе решение «какой код здесь исполняется» переходит к
организации (§8.1).

**Владелец организации** — `organizations.owner_login`, ровно один,
единственная операция — передача. Той же формы, что инвариант «последний
админ» в `admin_api.change_role`, и с той же проверкой check-then-act
одной транзакцией.

**Дыра, закрытая сразу** (§8.2 требует именно этого): если понизить
владельца может только он сам, организация с потерянным доступом остаётся
без владельца навсегда. Запасной путь ровно один — администратор
развёртывания может переназначить владельца. Без него «не может быть
понижен» превращается из гарантии в ловушку.
"""

from __future__ import annotations

from typing import Optional

from .repository import Repository


class OrganizationActionError(Exception):
    """Доменный отказ: 400 наружу (не про identity вызывающего)."""


def _require_org(repo: Repository, org_id: int) -> dict:
    org = repo.get_organization(org_id)
    if org is None:
        raise OrganizationActionError(f"Организация #{org_id} не найдена.")
    return org


def _require_user(repo: Repository, login: str):
    profile = repo.get_user_profile(login)
    if profile is None:
        raise OrganizationActionError(f"Пользователь {login!r} не найден.")
    return profile


# ---------- Начальная загрузка ----------

def ensure_bootstrapped(repo: Repository) -> dict:
    """
    Довести развёртывание до пригодного состояния. Идемпотентно.

    Нужна из-за порядка событий на СВЕЖЕЙ установке: миграция 014 создаёт
    организацию и помечает существующих админов как superuser, но на пустой
    БД админов ещё нет — они появляются позже, регистрацией. Без этой
    функции такое развёртывание осталось бы вовсе без администратора
    развёртывания, то есть без возможности ставить пакеты и выпускать
    релизы.

    Правило: если superuser'ов нет НИ ОДНОГО — им становится самый ранний
    админ. Это не «admin ⇒ superuser»: как только superuser появился,
    правило больше не срабатывает, и дальше флаг выдаётся только явно.
    Заодно организация без владельца получает владельцем первого superuser'а.

    Форма взята у `signing_keys.ensure_bootstrapped` — тот же приём и та же
    причина: состояние, без которого сервис бесполезен, должно заводиться
    само, а не обнаруживаться отказом.
    """
    result = {"superuser": None, "owner": None}
    if not repo.list_superusers():
        admins = [u.login for u in repo.list_users() if u.role == "admin"]
        if admins:
            repo.set_superuser(admins[0], True)
            result["superuser"] = admins[0]

    org_id = repo.default_organization_id()
    if org_id is not None:
        org = repo.get_organization(org_id)
        if org and not org["owner_login"]:
            supers = repo.list_superusers()
            if supers:
                repo.set_organization_owner(org_id, supers[0])
                result["owner"] = supers[0]
    return result


# ---------- Чтение ----------

def list_organizations(repo: Repository) -> dict:
    orgs = repo.list_organizations()
    for org in orgs:
        org["member_count"] = len(repo.organization_members(org["id"]))
    return {"organizations": orgs}


def get_organization(repo: Repository, org_id: int) -> dict:
    org = _require_org(repo, org_id)
    org["members"] = repo.organization_members(org_id)
    return org


# ---------- Управление ----------

def create_organization(repo: Repository, *, name: str,
                        parent_id: Optional[int] = None,
                        owner_login: Optional[str] = None) -> dict:
    """
    Завести организацию. Только администратор развёртывания.

    `parent_id` — форма без семантики (§8.3): иерархия
    университет → институт → кафедра заложена списком смежности, но
    НАСЛЕДОВАНИЯ НЕТ и появиться само оно не должно. Каскадирует ли выдача
    с уровня университета на кафедры, видит ли руководитель института
    содержимое кафедр — продуктовые решения, и принимать их вслепую хуже,
    чем не принимать.
    """
    clean = (name or "").strip()
    if not clean:
        raise OrganizationActionError("У организации должно быть имя.")
    if parent_id is not None:
        _require_org(repo, parent_id)
    if owner_login is not None:
        _require_user(repo, owner_login)
    org_id = repo.create_organization(clean, parent_id=parent_id,
                                      owner_login=owner_login)
    return repo.get_organization(org_id)


def rename_organization(repo: Repository, *, org_id: int, name: str) -> dict:
    _require_org(repo, org_id)
    clean = (name or "").strip()
    if not clean:
        raise OrganizationActionError("У организации должно быть имя.")
    repo.rename_organization(org_id, clean)
    return repo.get_organization(org_id)


def transfer_ownership(repo: Repository, *, org_id: int, new_owner: str,
                       actor_login: str, actor_is_superuser: bool) -> dict:
    """
    Передать владение организацией.

    Передать вправе сам владелец — или администратор развёртывания. Второй
    путь существует ровно для одного случая: организация осталась без
    доступного владельца (человек уволился, ушёл из вуза). Без него
    инвариант «владельца нельзя понизить» превращается в ловушку — чинить
    изнутри такую организацию нечем.

    Новый владелец обязан состоять В ЭТОЙ организации: владелец чужой
    организации — это уже не контейнер, а дыра в границе.
    """
    org = _require_org(repo, org_id)
    if not actor_is_superuser and org["owner_login"] != actor_login:
        raise OrganizationActionError(
            "Передать владение может владелец организации или "
            "администратор развёртывания.")
    profile = _require_user(repo, new_owner)
    if repo.user_organization_id(new_owner) != org_id:
        raise OrganizationActionError(
            f"{new_owner!r} не состоит в организации «{org['name']}»: "
            f"владельцем можно сделать только её участника.")
    if profile.role != "admin":
        raise OrganizationActionError(
            f"Владелец организации — администратор в ней; у {new_owner!r} "
            f"роль {profile.role!r}.")
    repo.set_organization_owner(org_id, new_owner)
    return repo.get_organization(org_id)


def move_user(repo: Repository, *, login: str,
              org_id: Optional[int]) -> dict:
    """
    Приём в организацию и исключение из неё.

    Перевод меняет ВЕСЬ видимый набор пользователя — ровно то, для чего
    строился `scope_version` (§8.1). Без инкремента десктоп продолжил бы
    жить с прежним набором предметов до первой правки контента.

    Владельца организации переводить нельзя, не передав владение: иначе
    организация осталась бы с владельцем со стороны.
    """
    _require_user(repo, login)
    if org_id is not None:
        _require_org(repo, org_id)

    current = repo.user_organization_id(login)
    if current is not None:
        org = repo.get_organization(current)
        if org and org["owner_login"] == login and current != org_id:
            raise OrganizationActionError(
                f"{login!r} — владелец организации «{org['name']}»; "
                f"сначала передайте владение.")

    repo.set_user_organization(login, org_id)
    repo.bump_scope_version(login)
    return {"login": login, "organization_id": org_id}


def set_default_access(repo: Repository, *, org_id: int, value: str) -> dict:
    """
    Умолчание видимости предметов — теперь у организации, а не одно на
    развёртывание: выдачи работают внутри организации, и умолчание для них
    обязано быть там же.
    """
    _require_org(repo, org_id)
    if value not in ("all", "none"):
        raise OrganizationActionError(
            f"default_subject_access: 'all'|'none', не {value!r}.")
    repo.set_organization_default_access(org_id, value)
    # Переключение меняет видимый набор у каждого, у кого нет явных выдач.
    for login in repo.organization_members(org_id):
        repo.bump_scope_version(login)
    return {"organization_id": org_id, "default_subject_access": value}


# ---------- Администратор развёртывания ----------

def set_superuser(repo: Repository, *, actor_login: str, target_login: str,
                  value: bool) -> dict:
    """
    Выдать или снять флаг администратора развёртывания.

    Инвариант «последний администратор» повторён здесь по той же причине и
    в той же форме: развёртывание без superuser'а нельзя починить изнутри —
    ставить пакеты, выпускать релизы и переназначать владельцев станет
    некому.

    Снять флаг с себя нельзя — не из вежливости, а чтобы единственный
    администратор не разжаловал себя одним нажатием.
    """
    _require_user(repo, target_login)
    if not value and target_login == actor_login:
        raise OrganizationActionError(
            "Нельзя снять флаг администратора развёртывания с себя.")
    if not value:
        supers = repo.list_superusers()
        if target_login in supers and len(supers) <= 1:
            raise OrganizationActionError(
                "Нельзя снять последнего администратора развёртывания.")
    repo.set_superuser(target_login, value)
    return {"login": target_login, "is_superuser": bool(value)}


__all__ = ["OrganizationActionError", "ensure_bootstrapped",
           "list_organizations", "get_organization", "create_organization",
           "rename_organization", "transfer_ownership", "move_user",
           "set_default_access", "set_superuser"]
