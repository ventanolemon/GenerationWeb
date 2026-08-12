"""
База знаний: разбор источников и правила, по которым она держится.

Модуль читает `docs/guide/*.md` и отвечает на один вопрос — что в базе
есть и по каким адресам. Оба потребителя (проверки и сборка веб-клиента)
берут ответ отсюда, чтобы «что считается разделом» не оказалось описано
дважды и по-разному.

Два правила формата и причины, по которым они такие
---------------------------------------------------
**Адрес объявлен, а не выведен.** Якорь не строится ни из заголовка, ни
из имени файла: ссылки на документацию расходятся по чатам и чужим
материалам, а формулировки заголовков правят постоянно. Выведенный якорь
ломался бы на каждой правке — и молча.

**Снимок экрана — идентификатор, а не путь.** `![…](shot:generator-main)`
разрешается в файл, который сделал генератор. Снимок, снятый руками,
устаревает беззвучно: на картинке остаётся кнопка, которой в продукте уже
нет, и ни один тест этого не покажет.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDE_DIR = ROOT / "docs" / "guide"
ANCHORS_FILE = GUIDE_DIR / "anchors.json"
SHOTS_FILE = GUIDE_DIR / "shots.json"
#: Куда генератор кладёт снимки: каталог, который веб отдаёт как есть.
SHOTS_DIR = ROOT / "frontend" / "public" / "guide"
#: Выгрузка для веб-клиента. Собирается скриптом, лежит в исходниках
#: фронтенда и попадает в сборку обычным импортом — базе знаний не нужен
#: ни сервер, ни сеть: она обязана открываться у гостя и в офлайне.
EXPORT_FILE = ROOT / "frontend" / "src" / "guide" / "content.json"

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*\{#([a-z0-9][a-z0-9-]*)\}\s*$",
                      re.M)
_BARE_HEADING = re.compile(r"^(#{2,3})\s+(?!.*\{#)(.+)$", re.M)
_SHOT = re.compile(r"!\[[^\]]*\]\(shot:([a-z0-9][a-z0-9-]*)\)")
_LINK = re.compile(r"\[[^\]]*\]\(guide:([a-z0-9][a-z0-9-]*(?:/[a-z0-9-]+)?)\)")
_ID = re.compile(r"\A[a-z0-9][a-z0-9-]*\Z")


class GuideError(ValueError):
    """Источник базы знаний нарушает формат."""


@dataclass
class Section:
    id: str            # адрес внутри страницы
    title: str
    level: int

    @property
    def anchor(self) -> str:
        return self.id


@dataclass
class Page:
    id: str
    title: str
    order: int
    body: str
    sections: list[Section] = field(default_factory=list)
    shots: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    source: str = ""

    def anchors(self) -> list[str]:
        return [self.id] + [f"{self.id}/{s.id}" for s in self.sections]


def _front_matter(text: str, source: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise GuideError(
            f"{source}: нет заголовочного блока с `id` и `title`. "
            f"Адрес страницы объявляется, а не выводится из имени файла.")
    meta: dict = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def parse_page(path: pathlib.Path) -> Page:
    raw = path.read_text(encoding="utf-8")
    source = path.name
    meta, body = _front_matter(raw, source)

    page_id = meta.get("id", "")
    if not _ID.match(page_id):
        raise GuideError(
            f"{source}: `id` страницы {page_id!r} — нужен непустой "
            f"идентификатор из строчных латинских букв, цифр и дефисов.")
    title = meta.get("title", "").strip()
    if not title:
        raise GuideError(f"{source}: у страницы нет `title`.")
    try:
        order = int(meta.get("order", "999"))
    except ValueError:
        raise GuideError(f"{source}: `order` должен быть числом.")

    bare = _BARE_HEADING.search(body)
    if bare is not None:
        raise GuideError(
            f"{source}: у заголовка «{bare.group(2).strip()}» нет "
            f"объявленного адреса. Допишите {{#идентификатор}} — иначе "
            f"ссылка на этот раздел сломается при первой правке заголовка.")

    sections = [Section(id=m.group(3), title=m.group(2), level=len(m.group(1)))
                for m in _HEADING.finditer(body)]
    seen: set[str] = set()
    for section in sections:
        if section.id in seen:
            raise GuideError(
                f"{source}: адрес {section.id!r} объявлен дважды.")
        seen.add(section.id)

    return Page(
        id=page_id, title=title, order=order, body=body, sections=sections,
        shots=sorted({m.group(1) for m in _SHOT.finditer(body)}),
        links=sorted({m.group(1) for m in _LINK.finditer(body)}),
        source=source,
    )


def load_pages(directory: pathlib.Path | None = None) -> list[Page]:
    """Все страницы базы, в порядке показа."""
    folder = directory or GUIDE_DIR
    pages = [parse_page(p) for p in sorted(folder.glob("*.md"))
             if p.name != "README.md"]
    pages.sort(key=lambda p: (p.order, p.id))
    return pages


def all_anchors(pages: Iterable[Page]) -> list[str]:
    out: list[str] = []
    for page in pages:
        out.extend(page.anchors())
    return out


def registry() -> list[str]:
    """Реестр опубликованных адресов (`anchors.json`)."""
    if not ANCHORS_FILE.exists():
        return []
    return list(json.loads(ANCHORS_FILE.read_text(encoding="utf-8")))


def generated_shots() -> list[str]:
    """Список снимков, которые сделал генератор (`shots.json`)."""
    if not SHOTS_FILE.exists():
        return []
    return list(json.loads(SHOTS_FILE.read_text(encoding="utf-8")))


def to_json() -> dict:
    """
    Выгрузка для веб-клиента: страницы, их разделы и текст.

    Разбор живёт здесь, а не в сборщике фронтенда, по той же причине, по
    которой правила портов живут в ядре: два разбора одного формата
    разойдутся, и разойдутся молча.
    """
    pages = load_pages()
    return {
        "pages": [
            {
                "id": p.id, "title": p.title, "order": p.order,
                "body": p.body,
                "sections": [
                    {"id": s.id, "title": s.title, "level": s.level}
                    for s in p.sections
                ],
            }
            for p in pages
        ],
    }
