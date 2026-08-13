"""
Служебные аккаунты: администратор развёртывания и владелец организации.

    python -m scripts.seed_accounts [--db ПУТЬ] [--password ПАРОЛЬ]

Зачем скриптом, а не «завести руками в базе». Пароль в скрипте можно
сменить одной командой и одинаково на обеих сторонах; аккаунт, заведённый
руками в одной базе, живёт только там и обнаруживается ровно тогда, когда
на другой машине не пускает.

ПРЕДУПРЕЖДЕНИЕ, которое нельзя прятать
--------------------------------------
Умолчания паролей лежат в открытом виде здесь, в репозитории. Это годится
для разработки и не годится ни для чего другого: перед выкладкой наружу
пароли обязаны быть сменены (`--password`, а лучше — из окружения). Скрипт
об этом печатает каждый раз, потому что предупреждение, которое читают
один раз при заведении, к моменту выкладки уже забыто.

Кто заводится
-------------
`dev` — администратор РАЗВЁРТЫВАНИЯ (`is_superuser`): пакеты узлов, ключи
подписи, выпуски, публичный API, примерка роли. Роль `admin` у него тоже
есть — иначе он не смог бы посмотреть административные экраны, ради
которых обычно и заходит.

`owner` — владелец организации: администратор своей организации и её
хозяин (передача владения, состав, умолчание видимости предметов). Флага
разработчика у него НЕТ намеренно: это разные оси (§8.2), и аккаунт, у
которого есть всё сразу, не даёт увидеть разницу — а увидеть её надо, она
объясняет половину прав в продукте.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.repository import Repository                   # noqa: E402

# Организации — серверное понятие; на десктопе модуля просто нет, и это
# не поломка, а разное устройство (одна копия базы на одного человека).
try:                                                     # noqa: SIM105
    from core import organizations_api
except ImportError:                                      # pragma: no cover
    organizations_api = None

DEV_LOGIN = "dev"
OWNER_LOGIN = "owner"
DEFAULT_DEV_PASSWORD = "dev-4Lab-2026"
DEFAULT_OWNER_PASSWORD = "own-4Lab-2026"


def seed(repo: Repository, *, dev_password: str = DEFAULT_DEV_PASSWORD,
         owner_password: str = DEFAULT_OWNER_PASSWORD) -> dict:
    """
    Завести оба аккаунта. Идемпотентно: повторный запуск чинит состояние,
    а не плодит вторых.

    Пароль существующему аккаунту НЕ переписывается: иначе запуск скрипта
    ради проверки молча сбрасывал бы пароль, который кто-то уже поменял.
    Для смены есть `--reset-password`.

    Скрипт работает и на СЕРВЕРНОЙ, и на ДЕСКТОПНОЙ базе, а они разные:
    у десктопа нет ни организаций, ни флага администратора развёртывания —
    там одна копия базы на одного человека, и делить в ней некого. Поэтому
    возможности проверяются по факту, а пропущенное НАЗЫВАЕТСЯ: молчаливый
    пропуск выглядел бы как «завёл, но почему-то не работает».
    """
    skipped = []
    if hasattr(repo, "ensure_users_table"):
        repo.ensure_users_table()
    if organizations_api is not None and hasattr(repo, "list_organizations"):
        organizations_api.ensure_bootstrapped(repo)
    else:
        skipped.append("организации (в этой базе их нет)")

    created = []
    for login, password, fio, role in (
        (DEV_LOGIN, dev_password, "Разработчик", "admin"),
        (OWNER_LOGIN, owner_password, "Владелец организации", "admin"),
    ):
        # Спрашиваем не «есть ли такой», а пробуем завести: `create_user`
        # сам отвечает False на занятый логин, и это единственный ответ,
        # одинаковый у обеих баз. Отдельная проверка существования уже
        # соврала однажды — на десктопе она приняла отказ «пустой пароль»
        # за «логин занят», и аккаунты не завелись молча.
        if _create(repo, login, password, fio, role):
            created.append(login)
        elif hasattr(repo, "set_user_role"):
            repo.set_user_role(login, role)

    # Администратор развёртывания — только `dev`.
    if hasattr(repo, "set_superuser"):
        repo.set_superuser(DEV_LOGIN, True)
    else:
        skipped.append("флаг разработчика (в этой базе его нет)")

    # Владение организацией. Берём ту, в которой аккаунт состоит: на свежей
    # установке это «Основная», заведённая миграцией.
    org_id = None
    if hasattr(repo, "user_organization_id"):
        org_id = repo.user_organization_id(OWNER_LOGIN)
        if org_id is not None:
            repo.set_organization_owner(org_id, OWNER_LOGIN)

    return {
        "created": created,
        "dev": DEV_LOGIN,
        "owner": OWNER_LOGIN,
        "organization_id": org_id,
        "skipped": skipped,
    }


def _create(repo, login: str, password: str, fio: str, role: str) -> bool:
    """Завести пользователя. False — логин уже занят (обе базы отвечают так)."""
    try:
        return bool(repo.create_user(login, password, fio, "", role=role))
    except TypeError:
        # Десктопная сигнатура: остальное — только по имени.
        return bool(repo.create_user(login, password, fio=fio, group="",
                                     role=role))


def main() -> int:
    parser = argparse.ArgumentParser(description="Служебные аккаунты")
    parser.add_argument("--db", default=None,
                        help="путь к БД (по умолчанию — из const.DB_PATH)")
    parser.add_argument("--dev-password", default=DEFAULT_DEV_PASSWORD)
    parser.add_argument("--owner-password", default=DEFAULT_OWNER_PASSWORD)
    parser.add_argument("--reset-password", action="store_true",
                        help="переписать пароли существующим аккаунтам")
    args = parser.parse_args()

    if args.db:
        db_path = pathlib.Path(args.db)
    else:
        from const import DB_PATH
        db_path = DB_PATH

    repo = Repository(db_path)
    result = seed(repo, dev_password=args.dev_password,
                  owner_password=args.owner_password)

    if args.reset_password:
        # Через смену пароля с проверкой старого нельзя: он как раз и
        # неизвестен. Пишем хэш напрямую тем же способом, что регистрация,
        # — иначе пришлось бы держать второй формат хранения пароля.
        if not hasattr(repo, "reset_user_password"):
            print("сброс пароля этой базой не поддерживается")
        else:
            for login, value in ((DEV_LOGIN, args.dev_password),
                                 (OWNER_LOGIN, args.owner_password)):
                repo.reset_user_password(login, value)
            print("пароли переписаны")

    print(f"база: {db_path}")
    print(f"заведено впервые: {result['created'] or '—'}")
    print(f"{DEV_LOGIN}: администратор развёртывания + admin")
    if result["organization_id"] is not None:
        print(f"{OWNER_LOGIN}: владелец организации "
              f"#{result['organization_id']}")
    else:
        print(f"{OWNER_LOGIN}: admin")
    for line in result["skipped"]:
        print(f"пропущено: {line}")
    print()
    print("ВНИМАНИЕ: пароли по умолчанию лежат в репозитории открытым "
          "текстом. Перед выкладкой наружу смените их: "
          "--dev-password/--owner-password --reset-password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
