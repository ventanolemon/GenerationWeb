"""
Произношение термина: транскрипция и звук, адресуемые ПО СЛОВУ.

Что это и откуда взялось
------------------------
Словарный тренажёр учит письменной форме слова, которого студент никогда
не слышал: английская орфография звучание не задаёт, и «hyperlink»,
выученный глазами, в речи не опознаётся. Поэтому у термина две
дополнительные записи:

* **транскрипция** — IPA-строка (`/ˈhaɪpəlɪŋk/`), 405 записей в
  `resources/transcriptions.json`;
* **звук** — заранее синтезированный WAV, 462 записи в
  `resources/audio/index.json`.

Обе готовятся ЗАРАНЕЕ (`tools/generate_transcriptions.py`,
`tools/generate_audio.py`) и лежат в поставке. Рантайм ничего не
синтезирует и о TTS не знает — иначе звук зависел бы от того, что
установлено на машине студента.

Почему в `core/`, а не в тренажёре
----------------------------------
Тот же довод, что у `word_tolerance`, `boolean_text`, `program_output`:
это понятие ПРЕДМЕТНОЙ ОБЛАСТИ, а не деталь одного упражнения. Показать
произношение обязаны и словарный диктант, и «выбери транскрипцию», и
веб-карточка ответа. Разложенное по вызывающим правило живёт до второго
вызывающего.

Адресация звука
---------------
Наружу отдаётся ИДЕНТИФИКАТОР `res:audio/<хеш>.wav`, а не путь. Путь
верен ровно на той машине, где файл сгенерировали; карточка с ответом
уезжает и на веб, и во второй десктоп, а `resources/` есть у обеих
сторон (см. `core/graph/resources.py`).

Отсутствие данных — норма
-------------------------
Ни транскрипция, ни звук не обязательны: словарь без них работает как
раньше. Поэтому все функции возвращают None, а не бросают, и каталоги
могут отсутствовать целиком.
"""

from __future__ import annotations

import json
import pathlib
from typing import Iterable, Mapping, Optional

#: Корень поставки. Тот же приём, что в `core/graph/resources.py`:
#: каталог ищется относительно кода, а не текущей рабочей папки.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
RESOURCES_DIR = _ROOT / "resources"

TRANSCRIPTIONS_PATH = RESOURCES_DIR / "transcriptions.json"
AUDIO_DIR = RESOURCES_DIR / "audio"
AUDIO_INDEX_PATH = AUDIO_DIR / "index.json"

#: Приставка идентификатора ресурса — та же, что у файлов графа.
AUDIO_PREFIX = "res:audio/"

_transcriptions: Optional[dict[str, str]] = None
_audio: Optional[dict[str, str]] = None
_audio_heads: Optional[dict[str, str]] = None


def _read(path: pathlib.Path) -> dict[str, str]:
    """Прочитать словарь `строка → строка`; любая беда — пустой словарь."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()}


def transcriptions() -> dict[str, str]:
    """Общая таблица `термин → IPA`. Читается один раз за процесс."""
    global _transcriptions
    if _transcriptions is None:
        _transcriptions = _read(TRANSCRIPTIONS_PATH)
    return _transcriptions


def audio_index() -> dict[str, str]:
    """
    Общая таблица `термин → идентификатор звука`.

    Манифест хранит имена файлов; наружу отдаются идентификаторы —
    так их можно класть в карточку ответа, не привязываясь к машине.
    Термины, для которых файла на диске нет, отбрасываются: кнопка,
    ведущая в никуда, хуже отсутствующей.
    """
    global _audio
    if _audio is None:
        _audio = {
            term: AUDIO_PREFIX + name
            for term, name in _read(AUDIO_INDEX_PATH).items()
            if (AUDIO_DIR / name).exists()
        }
    return _audio


def _audio_by_head() -> dict[str, str]:
    """
    Тот же манифест, но ключом — термин без скобочного пояснения.

    Строится один раз рядом с основным: запасной путь `audio_of` иначе
    перебирал бы весь манифест на каждый промах, а промах — это обычное
    дело (`coverage` спрашивает про каждый термин словаря).

    Первое вхождение побеждает, и порядок берётся из манифеста: два
    разных полных написания одного сокращения — случай, которого в
    поставке нет, а если появится, выбор должен быть предсказуемым, а не
    зависеть от порядка обхода словаря.
    """
    global _audio_heads
    if _audio_heads is None:
        _audio_heads = {}
        for term, resource in audio_index().items():
            head = _head(term)
            if head and head != term:
                _audio_heads.setdefault(head, resource)
    return _audio_heads


def reset_cache() -> None:
    """Сбросить прочитанное. Нужно тестам, подменяющим поставку."""
    global _transcriptions, _audio, _audio_heads
    _transcriptions = _audio = _audio_heads = None


def transcription_of(term: str,
                     inline: Mapping[str, str] | None = None,
                     ) -> Optional[str]:
    """
    IPA термина. Запись В САМОМ СЛОВАРЕ побеждает общую таблицу.

    Общая таблица собрана автоматически и местами приблизительна;
    `inline` — то, что автор словаря выверил руками. Правило «своё
    важнее общего» и есть способ такую правку закрепить.
    """
    if inline:
        own = inline.get(term)
        if own:
            return own
    return transcriptions().get(term)


def _head(term: str) -> str:
    """Термин без скобочного пояснения: «BIOS (Basic …)» → «BIOS»."""
    return str(term or "").split("(", 1)[0].strip()


def audio_of(term: str) -> Optional[str]:
    """
    Идентификатор звука термина; None — звука для него нет.

    Запасной путь: термин без скобочного пояснения. В одном словаре
    сокращение записано как «BIOS», в другом — как «BIOS (Basic
    Input/Output System)», и манифест адресует термин ПОСИМВОЛЬНО, то
    есть считает их разными словами. Замер: так теряли звук `BIOS`, `CPU`
    и `ROM` — при том что файл для них есть.

    Подмена законна не «потому что похоже», а по построению материала:
    `tools/generate_audio.py` СНИМАЕТ скобочное пояснение перед синтезом,
    поэтому в файле для «BIOS (Basic Input/Output System)» произнесено
    ровно «BIOS» (0.57 с — проверено длительностью, а не предположением).

    Обратной подмены нет: у полной записи свой ключ, и искать по ней
    короткую незачем.
    """
    found = audio_index().get(term)
    if found is not None:
        return found
    return _audio_by_head().get(_head(term))


def inline_transcriptions(data) -> dict[str, str]:
    """
    Достать поля `"transcription"` из словаря любого поддерживаемого вида.

    Возвращается только явно прописанное в самом файле; общая таблица
    накладывается отдельно — смешивать их здесь значило бы потерять
    различие между «автор выверил» и «сгенерировано скриптом».
    """
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return out
    vocabulary = data.get("vocabulary")
    if isinstance(vocabulary, list):
        for entry in vocabulary:
            if not isinstance(entry, dict):
                continue
            term, ipa = entry.get("term"), entry.get("transcription")
            if isinstance(term, str) and isinstance(ipa, str) and ipa.strip():
                out[term] = ipa
        return out
    units = data.get("units")
    if isinstance(units, list):
        for unit in units:
            out.update(inline_transcriptions(unit))
    return out


def coverage(terms: Iterable[str]) -> tuple[int, int, int]:
    """
    Сколько терминов обеспечено: `(всего, с транскрипцией, со звуком)`.

    Нужна не для работы, а для ПРОВЕРКИ работы: «звук есть» — это не про
    наличие каталога, а про то, какая доля словаря им покрыта.
    """
    words = [str(t) for t in terms]
    ipa, sound = transcriptions(), audio_index()
    return (len(words),
            sum(1 for t in words if t in ipa),
            sum(1 for t in words if t in sound))
