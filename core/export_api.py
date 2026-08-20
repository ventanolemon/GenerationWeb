"""
Сборка .docx: варианты и размещение ответов.

Экспорт умел ровно одно: N заданий подряд, ответ сразу под каждым, и
единственная настройка — булево `with_answers`. Преподавателю этого мало
по двум разным причинам, и обе видны на бумаге:

* **ответ под заданием виден студенту.** Раздавать такой лист нельзя;
  чтобы получить рабочий вариант, ответы нужно унести — в конец варианта
  (ключ для проверяющего отрывается), в конец файла (ключ печатается
  отдельной пачкой) или убрать совсем;
* **варианта как понятия не было вовсе.** «N заданий с разрывом страницы»
  — это не N вариантов: у варианта есть номер, он повторяет ОДИН И ТОТ ЖЕ
  набор тем разными числами, и ответы к нему собираются вместе.

Здесь и то, и другое. Модуль headless (как sync_api, grants_api): строит
документ из готовых заданий и ничего не знает ни про HTTP, ни про реестр
генераторов — поэтому раскладку можно проверить тестом, а не глазами.

Почему модуль ОБЩИЙ для сервера и десктопа
------------------------------------------
Раскладка ответов — понятие предметной области, а не деталь одного
клиента: «ключ отрывается вместе с концом варианта» значит одно и то же
всюду. Разложенное по вызывающим правило живёт до второго вызывающего, а
их здесь три — веб-служба и два бэкенда настольного приложения (через
python-docx и через Word по COM).

Три копии раскладки означали бы, что «в конце варианта» на десктопе и на
вебе однажды разойдутся, и разойдутся молча — тот же класс, что у
номеров разделов и у переключателя «Смотреть/Решать».

Что при этом РАЗНОЕ, и потому вынесено за скобки: механика письма.
python-docx умеет `add_heading`, у Word по COM есть `Selection`, и общего
у них нет ничего. Поэтому раскладка обращается не к документу, а к
**писцу** (`DocumentWriter`) — трём действиям, которые умеет каждая из
платформ: заголовок, разрыв страницы, блоки содержания.
"""

from __future__ import annotations

from typing import Iterable, Protocol, Sequence

from .task import StaticTask

#: Куда девать ответы. Порядок — от самого «преподавательского» к
#: студенческому.
ANSWER_PLACEMENTS = ("under", "variant_end", "file_end", "hidden")

_PLACEMENT_TITLES = {
    "under": "Ответ",
    "variant_end": "Ответы",
    "file_end": "Ответы",
}


class ExportError(ValueError):
    """Недопустимые параметры экспорта — роутер превращает в 400."""


class DocumentWriter(Protocol):
    """
    Три действия, которыми выражается любая раскладка.

    Меньше нельзя: без заголовков документ нечитаем, без разрыва страницы
    ключ не отрывается, без блоков нечего печатать. Больше не нужно —
    и это существенно: чем уже протокол, тем меньше платформа может
    просочиться в раскладку.
    """

    def heading(self, text: str, level: int) -> None: ...

    def page_break(self) -> None: ...

    def blocks(self, blocks: Iterable) -> None: ...


class PythonDocxWriter:
    """
    Писец поверх `python-docx`. Им пользуются веб-служба и настольный
    кросс-платформенный бэкенд — документ у них одинаковый.
    """

    def __init__(self, doc):
        self.doc = doc

    def heading(self, text: str, level: int) -> None:
        self.doc.add_heading(text, level=level)

    def page_break(self) -> None:
        self.doc.add_page_break()

    def blocks(self, blocks: Iterable) -> None:
        for block in blocks:
            block.render_docx(self.doc)


def build_document(
    doc,
    variants: Sequence[Sequence[StaticTask]],
    *,
    title: str,
    answers: str = "under",
) -> None:
    """
    Наполнить документ `python-docx` вариантами.

    Тонкая обёртка над `build_with`: документ создаёт вызывающий — так
    модуль не зависит от python-docx на уровне импорта и остаётся
    проверяемым подделкой.
    """
    build_with(PythonDocxWriter(doc), variants, title=title, answers=answers)


def build_with(
    writer: DocumentWriter,
    variants: Sequence[Sequence[StaticTask]],
    *,
    title: str,
    answers: str = "under",
) -> None:
    """
    Раскладка вариантов и ответов. Единственное место, где она описана.

    `variants` — список вариантов, каждый список заданий. Один вариант —
    обычный случай, и тогда заголовок «Вариант 1» не печатается: он
    сообщал бы о структуре, которой нет.
    """
    if answers not in ANSWER_PLACEMENTS:
        raise ExportError(
            f"Размещение ответов: {', '.join(ANSWER_PLACEMENTS)}; "
            f"не {answers!r}.")
    if not variants or not any(variants):
        raise ExportError("Нечего экспортировать: заданий нет.")

    writer.heading(title, 0)
    many = len(variants) > 1
    # Ответы для «в конце файла» копятся здесь: (подпись, блоки).
    tail: list[tuple[str, Sequence]] = []

    for v_index, tasks in enumerate(variants, start=1):
        if many:
            if v_index > 1:
                writer.page_break()
            writer.heading(f"Вариант {v_index}", 1)

        for t_index, task in enumerate(tasks, start=1):
            label = f"Задание {t_index}"
            writer.heading(label, 2)
            writer.blocks(task.statement)

            if answers == "under":
                writer.heading(f"Ответ {t_index}", 3)
                writer.blocks(task.answer)
            elif answers == "variant_end":
                pass                      # соберём ниже, после всех заданий
            elif answers == "file_end":
                caption = (f"Вариант {v_index}, задание {t_index}" if many
                           else label)
                tail.append((caption, task.answer))

            # Разрыв между заданиями — только когда вариант один: внутри
            # варианта задания идут подряд, иначе лист на задание.
            if not many and t_index < len(tasks):
                writer.page_break()

        if answers == "variant_end":
            writer.page_break()
            writer.heading(_PLACEMENT_TITLES["variant_end"], 2)
            for t_index, task in enumerate(tasks, start=1):
                writer.heading(f"Задание {t_index}", 3)
                writer.blocks(task.answer)

    if answers == "file_end" and tail:
        writer.page_break()
        writer.heading(_PLACEMENT_TITLES["file_end"], 1)
        for caption, blocks in tail:
            writer.heading(caption, 3)
            writer.blocks(blocks)


def normalise_placement(answers: str | None, with_answers: bool | None) -> str:
    """
    Совместимость со старым контрактом.

    `with_answers` был единственной настройкой, и его шлют три экрана
    фронта плюс десктоп. Пока они не обновлены, `true` означает прежнее
    поведение («под заданием»), `false` — «скрыть».
    """
    if answers:
        if answers not in ANSWER_PLACEMENTS:
            raise ExportError(
                f"Размещение ответов: {', '.join(ANSWER_PLACEMENTS)}; "
                f"не {answers!r}.")
        return answers
    if with_answers is False:
        return "hidden"
    return "under"


__all__ = ["ANSWER_PLACEMENTS", "ExportError", "DocumentWriter",
           "PythonDocxWriter", "build_document", "build_with",
           "normalise_placement"]
