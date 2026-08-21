"""
Правка страниц базы знаний из приложения — поверх поставки.

Развилка, пройденная явно
-------------------------
`docs/handbook/04-stubs.md` §7 записывал выбор так: «хранить страницы в
БД поверх поставки (страница из сборки — умолчание, БД хранит
изменённые)». Здесь это и сделано, и слово «поверх» — существенное.

Почему НЕ перенести страницы в базу целиком. База знаний вкомпилирована
в сборку ради одного свойства: она открывается **у гостя и без сети**, то
есть ровно тогда, когда что-то не работает и человеку нужна инструкция.
Перенос в базу отнял бы это свойство — документация перестала бы
открываться в тот единственный момент, ради которого она написана.

Отсюда устройство: поставка — умолчание, таблица хранит только
ИЗМЕНЁННЫЕ страницы. Пустая таблица означает «правок нет», и клиент
показывает то, что собрано в `content.json`. Сеть при этом нужна, чтобы
УВИДЕТЬ правки, а не чтобы увидеть документацию.

Правка проходит ту же проверку формата
--------------------------------------
Текст из редактора разбирается `guide.parse_text` — тем же кодом, что и
файлы поставки. Это не перестраховка: набор разметки закрыт намеренно
(§8 того же документа), и страница с таблицей или с заголовком без
объявленного адреса сломалась бы у всех читателей сразу, а автор правки
узнал бы об этом последним.

Поэтому отказ здесь — с ПРИЧИНОЙ на языке автора: «таблицы веб-клиент не
показывает», а не «ошибка сохранения».

Кто правит
----------
Администратор (`role == "admin"`) и разработчик (`users.is_superuser`).
Преподаватель — нет, и это отличается от прав на СОДЕРЖАНИЕ ЗАДАНИЙ
(`content_authz`, где `teacher` полноправен): предмет преподавателя —
его собственный, а страница базы знаний одна на всю установку, и правит
её тот, кто отвечает за установку целиком.

Модуль headless (как `grants_api`, `sync_api`, `export_api`): чистая
логика без HTTP, поэтому правила проверяются прогоном, а не через
клиент.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from . import guide
from .repository import Repository

#: Роли, которым можно править базу знаний.
EDITOR_ROLES = ("admin",)


class GuideAccessError(PermissionError):
    """Роль не имеет права править базу знаний — роутер превращает в 403."""


class GuideEditError(ValueError):
    """Правка не проходит по формату или адресу — роутер превращает в 400."""


def may_edit(repo: Repository, actor: Optional[str],
             role: Optional[str]) -> bool:
    """
    Может ли этот человек править страницы.

    Разработчик опознаётся по `is_superuser`, а не по роли: роль
    приходит из сессии и описывает, ЧТО человек сейчас делает, а
    `is_superuser` — свойство учётной записи в базе. Для права,
    действующего на всю установку, надёжнее второе.
    """
    if role in EDITOR_ROLES:
        return True
    if not actor:
        return False
    try:
        return bool(repo.is_superuser(actor))
    except Exception:                       # noqa: BLE001
        return False


def require_editor(repo: Repository, actor: Optional[str],
                   role: Optional[str]) -> None:
    if not may_edit(repo, actor, role):
        raise GuideAccessError(
            "Править базу знаний могут администратор и разработчик. "
            "Страница одна на всю установку, поэтому право не выдаётся "
            "по предметам.")


# ---------------------------------------------------------------- чтение

def overrides(repo: Repository) -> dict[str, dict]:
    """Правки из базы: `адрес страницы → запись`. Снятые не попадают."""
    with repo.transaction() as conn:
        rows = conn.execute(
            "SELECT page_id, title, body, updated_at, updated_by "
            "FROM guide_pages WHERE deleted = 0").fetchall()
    return {
        row[0]: {"id": row[0], "title": row[1], "body": row[2],
                 "updated_at": row[3], "updated_by": row[4]}
        for row in rows
    }


def shipped() -> dict[str, dict]:
    """Страницы поставки в том же виде, что отдаёт сборка клиенту."""
    return {page["id"]: page for page in guide.to_json()["pages"]}


def merged(repo: Repository) -> list[dict]:
    """
    Страницы для показа: поставка, поверх которой легли правки.

    Порядок берётся у ПОСТАВКИ и правкой не меняется: `order` объявлен в
    заголовочном блоке файла, и позволить менять его из редактора значило
    бы завести второй источник порядка.

    У каждой страницы появляется `edited` — правлена ли она. Читателю это
    не нужно, редактору нужно: без пометки «вернуть к поставке» нечего
    предложить, а вернуть иногда единственный выход.
    """
    base = shipped()
    changes = overrides(repo)
    out: list[dict] = []
    for page_id, page in base.items():
        change = changes.get(page_id)
        if change is None:
            out.append({**page, "edited": False})
            continue
        parsed = guide.parse_text(_with_front_matter(change, page), page_id)
        out.append({
            "id": page_id,
            "title": change["title"],
            "order": page["order"],
            "body": change["body"],
            "sections": [{"id": s.id, "title": s.title, "level": s.level}
                         for s in parsed.sections],
            "edited": True,
            "updated_at": change["updated_at"],
            "updated_by": change["updated_by"],
        })
    out.sort(key=lambda page: (page.get("order", 999), page["id"]))
    return out


def _with_front_matter(change: dict, page: dict) -> str:
    """
    Собрать источник страницы для разбора.

    Заголовочный блок восстанавливается из полей записи: в базе он не
    хранится, потому что `id` и `order` правке не подлежат, а `title`
    лежит отдельной колонкой. Хранить его строкой означало бы дать двум
    источникам возможность разойтись.
    """
    return (f"---\nid: {page['id']}\ntitle: {change['title']}\n"
            f"order: {page.get('order', 999)}\n---\n{change['body']}")


# ---------------------------------------------------------------- запись

def save(repo: Repository, page_id: str, *, title: str, body: str,
         actor: str) -> dict:
    """
    Сохранить правку страницы. Возвращает её же в виде для показа.

    Править можно только СУЩЕСТВУЮЩУЮ страницу поставки. Заведение новых
    страниц из приложения намеренно не сделано: у страницы есть адрес,
    адрес попадает в чужие материалы и в ссылки `guide:`, а реестр
    адресов (`anchors.json`) лежит в репозитории и проверяется прогоном.
    Новая страница мимо реестра — это ссылка, которая ломается молча.
    """
    base = shipped()
    if page_id not in base:
        raise GuideEditError(
            f"Страницы {page_id!r} нет в поставке. Из приложения правят "
            f"существующие страницы; новые заводят в репозитории — там "
            f"лежит реестр адресов, по которому проверяются ссылки.")

    title = (title or "").strip()
    if not title:
        raise GuideEditError("У страницы должен быть заголовок.")

    # Разбор ДО записи: сломанную страницу нельзя сохранить даже на миг.
    try:
        parsed = guide.parse_text(
            _with_front_matter({"title": title, "body": body}, base[page_id]),
            page_id)
    except guide.GuideError as exc:
        raise GuideEditError(str(exc)) from exc

    _check_links(parsed, base)

    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    with repo.transaction() as conn:
        conn.execute(
            "INSERT INTO guide_pages "
            "  (page_id, title, body, updated_at, updated_by, deleted) "
            "VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(page_id) DO UPDATE SET "
            "  title = excluded.title, body = excluded.body, "
            "  updated_at = excluded.updated_at, "
            "  updated_by = excluded.updated_by, deleted = 0",
            (page_id, title, body, now, actor))
    return {"id": page_id, "title": title, "body": body,
            "updated_at": now, "updated_by": actor, "edited": True}


def reset(repo: Repository, page_id: str) -> bool:
    """
    Вернуть страницу к поставочной. `False` — правки и не было.

    Строка помечается снятой, а не удаляется: «правку сняли» и «правки не
    было» — разные события, и различать их надо по журналу, а не по
    памяти администратора.
    """
    with repo.transaction() as conn:
        cursor = conn.execute(
            "UPDATE guide_pages SET deleted = 1 "
            "WHERE page_id = ? AND deleted = 0", (page_id,))
        return bool(cursor.rowcount)


def _check_links(parsed: guide.Page, base: dict) -> None:
    """
    Ссылки `guide:` обязаны вести на существующий адрес.

    Проверка та же, что у прогона по источникам поставки, и по той же
    причине: ссылка, ведущая в никуда, ломается молча — читатель просто
    попадает на пустую страницу и решает, что документации нет.
    """
    known: set[str] = set()
    for page in base.values():
        known.add(page["id"])
        for section in page.get("sections", []):
            known.add(f"{page['id']}/{section['id']}")
    known.update(parsed.anchors())

    unknown = sorted(set(parsed.links) - known)
    if unknown:
        raise GuideEditError(
            "Ссылка ведёт на несуществующий адрес: "
            + ", ".join(unknown)
            + ". Адрес — это `страница` или `страница/раздел`.")


__all__ = [
    "EDITOR_ROLES", "GuideAccessError", "GuideEditError",
    "may_edit", "require_editor", "merged", "overrides", "shipped",
    "save", "reset",
]
