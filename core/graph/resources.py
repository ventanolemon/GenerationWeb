"""
Ресурсы поставки: адресация файлов по ИДЕНТИФИКАТОРУ, а не по пути.

Зачем это понадобилось
----------------------
Четыре узла берут данные из файла (`words_file`, `sentences_file`,
`image_file`, `pool`), и файл до сих пор задавался путём — тем, что
вернул диалог выбора на машине автора. Замер: граф, собранный на
десктопе, на сервере падает.

    words_file: "/home/teacher/Documents/words.json"
    → GraphValidationError: Файл со словами не найден

Это не «на вебе неудобно», как было записано, а «граф с файлом не
переживает границу синка» — в обе стороны и молча до самой выдачи
задания. Путь машинно-локален по своей природе: он верен ровно на одной
машине и бессмыслен на любой другой.

Решение
-------
Идентификатор вместо пути: `res:words/unit1_history.json` разрешается
относительно каталога `resources/` ТОЙ машины, которая исполняет граф.
Обе стороны поставляют один и тот же `resources/`, поэтому такой граф
работает всюду одинаково — не потому, что путь совпал, а потому, что
пути в нём нет.

Обычный путь при этом продолжает работать: у десктопа есть свои файлы,
которых нет в поставке, и запрещать их означало бы сломать существующие
графы ради красоты. Разница названа честно — путь остаётся локальным,
идентификатор переносим.

Границы
-------
Здесь только ПОСТАВОЧНЫЕ ресурсы: то, что лежит в `resources/` рядом с
приложением. Загрузка своих файлов на сервер (хранение, квоты, чьё это и
кому видно) — отдельная работа, упирающаяся в продуктовые решения, а не в
код; см. open_items §3.1.
"""

from __future__ import annotations

import pathlib
from typing import Iterable, NamedTuple

from .errors import GraphValidationError

#: Приставка, отличающая идентификатор от пути. Двоеточие выбрано не
#: случайно: на Windows путь тоже содержит двоеточие (`C:\…`), но во
#: второй позиции, а здесь — после непустого имени схемы из букв.
PREFIX = "res:"

_ROOT = pathlib.Path(__file__).resolve().parents[2]
RESOURCES_DIR = _ROOT / "resources"

#: Вид ресурса → каталог внутри resources/ и расширения. Список закрытый:
#: он же служит белым списком того, что вообще можно адресовать.
KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "words": ("words", (".json",)),
    "sentences": ("words", (".json",)),
    "images": ("images", (".png", ".jpg", ".jpeg", ".bmp", ".gif")),
    "pools": ("pools", (".json", ".txt", ".csv")),
    # Произношение терминов, подготовленное заранее (tools/generate_audio.py).
    # Адресуется идентификатором по той же причине, что и остальное: путь к
    # WAV верен на машине, где его сгенерировали, и бессмыслен на любой
    # другой — а карточка с ответом уезжает на веб и в другой десктоп.
    "audio": ("audio", (".wav",)),
}


class Resource(NamedTuple):
    """Поставочный файл, каким его видит автор графа."""
    id: str            # «res:words/unit1_history.json» — то, что идёт в граф
    kind: str          # words | sentences | images | pools
    name: str          # имя файла
    title: str         # человекочитаемое имя для списка


def is_resource_id(value: str) -> bool:
    return str(value or "").startswith(PREFIX)


def _relative(value: str) -> str:
    return str(value or "")[len(PREFIX):].strip()


def resolve(value: str) -> pathlib.Path:
    """
    Значение файлового параметра → путь на этой машине.

    Идентификатор разрешается внутри `resources/`, обычный путь остаётся
    собой. Выход за пределы `resources/` — отказ, а не срезанные `..`:
    идентификатор приезжает из графа, а граф приезжает по синку от чужой
    установки, и «прочитать любой файл, до которого дотянется процесс» —
    не та возможность, которую стоит давать значению в JSON. Молча
    исправить такой идентификатор тоже нельзя: исправленный он укажет не
    туда, куда просили, и разбираться будут с загадкой, а не с отказом.
    """
    raw = str(value or "").strip()
    if not is_resource_id(raw):
        return pathlib.Path(raw)
    rel = _relative(raw)
    if not rel:
        raise GraphValidationError(f"Пустой идентификатор ресурса: {raw!r}")
    # Идентификатор всегда относительный. `res:/etc/passwd` не срезается до
    # `etc/passwd`: срезанный он указывает не туда, куда написано, и вместо
    # отказа автор получил бы загадку — «файл не найден», хотя файл есть.
    if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
        raise GraphValidationError(
            f"Идентификатор ресурса {raw!r} должен быть относительным.")
    base = RESOURCES_DIR.resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise GraphValidationError(
            f"Идентификатор ресурса {raw!r} ведёт за пределы поставки.")
    return target


def describe(value: str) -> str:
    """Как назвать файл в сообщении об ошибке — идентификатором или путём."""
    raw = str(value or "").strip()
    return raw if is_resource_id(raw) else repr(raw)


def _title(kind: str, path: pathlib.Path) -> str:
    stem = path.stem.replace("_", " ")
    return f"{stem} ({path.suffix.lstrip('.')})" if kind == "pools" else stem


def _suits(kind: str, path: pathlib.Path) -> bool:
    """
    Слова и предложения лежат в ОДНОЙ папке и различаются содержимым, а не
    именем или расширением. Поэтому список для `words_file` и список для
    `sentences_file` приходится разделять чтением файла — иначе автору
    предложат словарь там, где нужен набор предложений, и узел упадёт уже
    при выдаче задания.

    Нераспознанный файл показывается в обоих списках: пусть лучше в
    списке будет лишнее, чем нужное туда не попадёт.
    """
    if kind not in ("words", "sentences"):
        return True
    try:
        from exercises.english.generators import _detect_kind
        detected = _detect_kind(path)
    except Exception:
        return True
    if detected not in ("words", "sentences"):
        return True
    return detected == kind


def available(kinds: Iterable[str] | None = None) -> list[Resource]:
    """
    Что есть в поставке. Порядок устойчивый — список показывают человеку.

    Отсутствующий каталог — не ошибка: часть видов ресурсов может не
    поставляться вовсе, и падать на этом означало бы уронить каталог
    узлов из-за пустой папки.
    """
    out: list[Resource] = []
    for kind in (kinds if kinds is not None else KINDS):
        entry = KINDS.get(kind)
        if entry is None:
            continue
        folder, suffixes = entry
        directory = RESOURCES_DIR / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if not _suits(kind, path):
                continue
            out.append(Resource(
                id=f"{PREFIX}{folder}/{path.name}",
                kind=kind,
                name=path.name,
                title=_title(kind, path),
            ))
    return out
