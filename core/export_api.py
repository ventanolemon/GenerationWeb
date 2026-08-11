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
"""

from __future__ import annotations

from typing import Iterable, Sequence

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


def _heading(doc, text: str, level: int) -> None:
    doc.add_heading(text, level=level)


def _render(doc, blocks: Iterable) -> None:
    for block in blocks:
        block.render_docx(doc)


def build_document(
    doc,
    variants: Sequence[Sequence[StaticTask]],
    *,
    title: str,
    answers: str = "under",
) -> None:
    """
    Наполнить `doc` вариантами. Документ создаёт вызывающий — так модуль
    не зависит от python-docx на уровне импорта и остаётся проверяемым
    подделкой.

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

    _heading(doc, title, 0)
    many = len(variants) > 1
    # Ответы для «в конце файла» копятся здесь: (подпись, блоки).
    tail: list[tuple[str, Sequence]] = []

    for v_index, tasks in enumerate(variants, start=1):
        if many:
            if v_index > 1:
                doc.add_page_break()
            _heading(doc, f"Вариант {v_index}", 1)

        for t_index, task in enumerate(tasks, start=1):
            label = f"Задание {t_index}"
            _heading(doc, label, 2)
            _render(doc, task.statement)

            if answers == "under":
                _heading(doc, f"Ответ {t_index}", 3)
                _render(doc, task.answer)
            elif answers == "variant_end":
                pass                      # соберём ниже, после всех заданий
            elif answers == "file_end":
                caption = (f"Вариант {v_index}, задание {t_index}" if many
                           else label)
                tail.append((caption, task.answer))

            # Разрыв между заданиями — только когда вариант один: внутри
            # варианта задания идут подряд, иначе лист на задание.
            if not many and t_index < len(tasks):
                doc.add_page_break()

        if answers == "variant_end":
            doc.add_page_break()
            _heading(doc, _PLACEMENT_TITLES["variant_end"], 2)
            for t_index, task in enumerate(tasks, start=1):
                _heading(doc, f"Задание {t_index}", 3)
                _render(doc, task.answer)

    if answers == "file_end" and tail:
        doc.add_page_break()
        _heading(doc, _PLACEMENT_TITLES["file_end"], 1)
        for caption, blocks in tail:
            _heading(doc, caption, 3)
            _render(doc, blocks)


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


__all__ = ["ANSWER_PLACEMENTS", "ExportError", "build_document",
           "normalise_placement"]
