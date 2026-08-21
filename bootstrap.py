"""
Bootstrap — единственное место, где соединяются ядро, БД и доменные модули.

Обязанности:
  1. Sync БД: гарантирует наличие subjects (Линал, Матан, Производные, Пределы,
     Английский, Физика, Кинематика, СCУАР, ОПВС) и записей в Partitions
     для всех code-only генераторов.
  2. Build registry: собирает GeneratorRegistry, регистрирует одиночные
     генераторы, фабрики физики/групп/тестов и интерактивные модули.

Этот модуль — единственное место в проекте, где явно указано,
к какому предмету относится каждый code-only генератор.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Optional

from core import (
    Capability, GeneratorRegistry, Repository, TaskGenerator,
    GroupGenerator, TestGenerator, WordStatsStore,
)
from core import partition_ids

from exercises.linal.generators import (
    Linal2DGenerator, Linal3DGenerator,
)
from exercises.matan.generators import (
    diff_generators, limits_generators,
)
from exercises.opvs.generators import (
    LogicCircuitGenerator, CCodeMistakesGenerator,
)
from exercises.fisic import FisicConstructorGenerator
from exercises.graph import GraphConstructorGenerator
from exercises.model_tasks import TASKS as MODEL_TASKS
from exercises.english.generators import english_generators_for_path


# Поставщик текущего user_id. Передаётся замыканием из main.py.
UserIdProvider = Callable[[], Optional[str]]


# ---------- Конфигурация: какой code-генератор к какому subject_id ----------

CODE_GENERATORS = [
    # ----- Линал (subject 1) -----
    (1, Linal2DGenerator()),
    (1, Linal3DGenerator()),

    # ----- Производные (subject 10) -----
    *[(10, g) for g in diff_generators()],

    # ----- Пределы (subject 8) -----
    *[(8, g) for g in limits_generators()],

    # ----- ОПВС (subject 11) -----
    (11, LogicCircuitGenerator(partition_id=70)),
    (11, CCodeMistakesGenerator(partition_id=71)),
]


# ---------- Sync БД ----------

def sync_database(repo: Repository, words_dir: Path) -> None:
    """
    Гарантировать существование всех subjects и code-only разделов в БД.
    Вызывать при старте приложения, перед build_registry.
    """
    repo.ensure_subject(1, "Линейная алгебра",       "Линейная алгебра")
    repo.ensure_subject(2, "Английский",             "Английский")
    repo.ensure_subject(3, "Физика",                 "Физика")
    repo.ensure_subject(8, "Пределы",                "Математический анализ")
    repo.ensure_subject(9, "Математический анализ",  "Математический анализ")
    repo.ensure_subject(10, "Производные",           "Математический анализ")
    repo.ensure_subject(11, "ОПВС",                  "ОПВС")

    # Таблица users: создаём если отсутствует, добавляем колонки профиля.
    repo.ensure_users_table()
    # Таблица WordStats для межсессионной памяти словарного тренажёра.
    repo.ensure_word_stats_table()

    for subject_id, gen in CODE_GENERATORS:
        if gen.partition_id is None:
            continue
        repo.ensure_code_partition(
            partition_id=gen.partition_id,
            subject_id=subject_id,
            name=gen.name,
        )

    # Задания на моделях (exercises/model_tasks): разделы-графы, которые
    # поставляются вместе с приложением. Заводятся РЯДОМ со старыми
    # код-генераторами, а не вместо них: замена сменила бы содержимое уже
    # выданных домашних заданий и разошлась бы со статистикой попыток.
    for entry in MODEL_TASKS.values():
        repo.ensure_graph_partition(
            partition_id=entry["partition_id"],
            subject_id=entry["subject_id"],
            name=entry["title"],
            graph=entry["graph"],
        )

    _repair_physics_constructor(repo)

    # Английские словари. Номер выводится из ИМЕНИ файла (см.
    # core/partition_ids.py), а не из его места в отсортированном списке:
    # каталоги сервера (20 файлов) и десктопа (12) разной длины, и при
    # старой схеме один и тот же номер означал разные словари. Перенос
    # существующих установок — миграция 015.
    if words_dir.exists():
        from exercises.english.generators import _detect_kind
        for path in sorted(words_dir.glob("*.json")):
            repo.ensure_code_partition(
                partition_id=partition_ids.english_words_id(path.stem),
                subject_id=2,
                name=_english_display_name(path),
            )
            # Разбор транскрипции — ВТОРОЙ раздел того же файла, в своей
            # полосе номеров. Рядом со словарём, а не вместо него: это
            # другое упражнение на том же материале.
            if _detect_kind(path) == "words" and _has_transcriptions(path):
                repo.ensure_code_partition(
                    partition_id=partition_ids.english_transcription_id(
                        path.stem),
                    subject_id=2,
                    name=_english_transcription_name(path),
                )
            # Произношение — ТРЕТИЙ раздел того же файла. Заводится только
            # там, где есть звук: правило приёма сравнивает запись с
            # эталонами, и раздел без них обещал бы проверку, которой нет.
            if _detect_kind(path) == "words" and _has_audio(path):
                repo.ensure_code_partition(
                    partition_id=partition_ids.english_pronunciation_id(
                        path.stem),
                    subject_id=2,
                    name=_english_pronunciation_name(path),
                )


def _english_transcription_name(path: Path) -> str:
    """Имя раздела «выбери транскрипцию» для этого словаря."""
    return f"Английский: {path.stem} (транскрипция)"


def _english_pronunciation_name(path: Path) -> str:
    """Имя раздела «произнесите вслух» для этого словаря."""
    return f"Английский: {path.stem} (произношение)"


def _has_audio(path: Path) -> bool:
    """
    Есть ли в словаре хоть один термин с готовым эталоном произношения.

    Проверка того же рода, что `_has_transcriptions`, и по той же причине:
    раздел, который на первом же клике говорит «здесь ничего нет», хуже
    отсутствующего раздела.
    """
    from exercises.english.generators import (
        WordsTrainerGenerator, _read_json_lenient,
    )
    from core import pronunciation
    try:
        data = _read_json_lenient(path)
        words = WordsTrainerGenerator._flatten_words(data)
    except Exception:                       # noqa: BLE001
        return False
    return any(pronunciation.audio_of(term) for term in words)


def _has_transcriptions(path: Path) -> bool:
    """
    Есть ли в словаре хоть один термин с известной транскрипцией.

    Проверка не косметическая: раздел без единого термина показывал бы
    задание «здесь ничего нет», а раздела, которого нет, никто и не
    обещал.
    """
    from exercises.english.generators import (
        WordsTrainerGenerator, _read_json_lenient,
    )
    from core import pronunciation
    try:
        data = _read_json_lenient(path)
        words = WordsTrainerGenerator._flatten_words(data)
    except Exception:                       # noqa: BLE001
        return False
    inline = pronunciation.inline_transcriptions(data)
    return any(pronunciation.transcription_of(t, inline) for t in words)


#: Настройка, которой поставочный раздел «конструктор» предмета Физика
#: не имел никогда. Второй закон Ньютона взят не как «какая-нибудь
#: задача», а как пример из документации самого конструктора
#: (`exercises/fisic/fisic_generater.py`): раздел из поставки обязан
#: показывать, что конструктор умеет, — иначе первое, что видит
#: преподаватель, это пустая форма.
_PHYSICS_CONSTRUCTOR_DEFAULT = {
    "condition": "Тело массой #m# движется с ускорением #a#. "
                 "Найдите действующую на него силу.",
    "result_letter": "F",
    "formula": "m * a",
    "dimension": "Н",
    "variables": {
        "m": {"min": 1, "max": 20, "kind": "natural", "dimension": "кг"},
        "a": {"min": 1, "max": 10, "kind": "natural", "dimension": "м/с^2"},
    },
}


def _repair_physics_constructor(repo: Repository) -> bool:
    """
    Починить поставочный раздел «конструктор» предмета Физика.

    В БД он лежит с `constracted = 0` — то есть заявляет, что его
    обслуживает КОД, — но код-генератора с его номером нет и не было.
    Клик по нему даёт `KeyError: Нет генератора для partition_id=2`.
    По имени и предмету это конструктор физики, то есть `constracted = 1`.

    Правка осторожная: трогаем только запись, которая ещё не настроена
    (пустые параметры). Настроенный раздел — уже работа преподавателя, и
    перезаписывать её нельзя, даже если `constracted` выглядит странно.
    """
    for part in repo.list_partitions_for_subject(3):
        if part.constracted != 0 or part.generation_params:
            continue
        if "конструктор" not in part.name.lower():
            continue
        # Без явного id: серверный upsert находит запись по паре
        # (предмет, имя) и правит её на месте, сохраняя номер. Это то,
        # что нужно, — раздел уже существует, у него меняется только
        # признак обслуживания и настройка.
        repo.upsert_partition(
            subject_id=3,
            name=part.name,
            constracted=1,
            generation_params=_PHYSICS_CONSTRUCTOR_DEFAULT,
        )
        return True
    return False


def english_partition_ids(words_dir: Path) -> dict[str, int]:
    """
    Номера разделов словарей: `имя файла → id`. Одна функция на sync и на
    сборку реестра — разойтись им нельзя, иначе раздел в БД окажется без
    генератора.
    """
    stems = [p.stem for p in sorted(words_dir.glob("*.json"))]
    return partition_ids.assign(stems, partition_ids.ENGLISH_WORDS)


def _english_display_name(path: Path) -> str:
    """Имя раздела для отображения в БД и UI."""
    from exercises.english.generators import _detect_kind
    kind = _detect_kind(path)
    if kind == "sentences":
        return f"Английский: {path.stem} (предложения)"
    return f"Английский: {path.stem}"


# ---------- Сборка реестра ----------

def build_registry(
    repo: Repository,
    words_dir: Path,
    *,
    stats_store: WordStatsStore | None = None,
    user_id_provider: UserIdProvider | None = None,
) -> GeneratorRegistry:
    registry = GeneratorRegistry()

    # 1. Code-only генераторы
    for _subject_id, gen in CODE_GENERATORS:
        if gen.partition_id is not None:
            registry.register(gen)

    # 2. Английские словари
    if words_dir.exists():
        from exercises.english.generators import (
            PronunciationGenerator, TranscriptionChoiceGenerator, _detect_kind,
        )
        for path in sorted(words_dir.glob("*.json")):
            pid = partition_ids.english_words_id(path.stem)
            display = _english_display_name(path)
            gen = english_generators_for_path(
                path, pid, name=display,
                stats_store=stats_store,
                user_id_provider=user_id_provider,
            )
            if gen is not None:
                registry.register(gen)
            if _detect_kind(path) == "words" and _has_transcriptions(path):
                registry.register(TranscriptionChoiceGenerator(
                    name=_english_transcription_name(path),
                    words_path=path,
                    partition_id=partition_ids.english_transcription_id(
                        path.stem),
                ))
            if _detect_kind(path) == "words" and _has_audio(path):
                registry.register(PronunciationGenerator(
                    name=_english_pronunciation_name(path),
                    words_path=path,
                    partition_id=partition_ids.english_pronunciation_id(
                        path.stem),
                ))

    # 3. БД: фабрики для физики, групп, тестов
    for subj in repo.list_subjects():
        for part in repo.list_partitions_for_subject(subj.id):
            if registry.has(part.id):
                continue
            if part.constracted == 1:
                _register_fisic(registry, part)
            elif part.constracted == 2:
                _register_group(registry, repo, part)
            elif part.constracted == 3:
                _register_test(registry, repo, part)
            elif part.constracted == 4:
                _register_graph(registry, part)

    return registry


# ---------- Фабрики ----------

def _register_fisic(registry: GeneratorRegistry, part) -> None:
    """Раздел-конструктор физики. Конфиг передаётся как dict."""
    config_dict = part.generation_params
    # Если конфиг был не-JSON (хранится под "raw") — попытаемся распарсить.
    if "raw" in config_dict:
        try:
            config_dict = json.loads(config_dict["raw"])
        except (json.JSONDecodeError, TypeError):
            config_dict = {}

    def factory(_params: dict, _pid=part.id, _name=part.name, _cfg=config_dict):
        return FisicConstructorGenerator(
            partition_id=_pid, name=_name, config=_cfg
        )

    registry.register_factory(part.id, factory)


def _register_graph(registry: GeneratorRegistry, part) -> None:
    """Раздел-граф (constracted=4, graph_addon.md Фаза 1): партиция хранит
    GraphSpec-словарь, адаптер исполняет его движком core/graph."""
    def factory(_params: dict, _pid=part.id, _name=part.name,
                _cfg=part.generation_params):
        return GraphConstructorGenerator(
            partition_id=_pid, name=_name, config=_cfg
        )

    registry.register_factory(part.id, factory)


def _register_group(registry: GeneratorRegistry, repo: Repository, part) -> None:
    raw = part.generation_params

    def factory(_params: dict, _registry=registry, _repo=repo,
                _pid=part.id, _name=part.name, _raw=raw):
        items = _raw.get("data") if isinstance(_raw, dict) and "data" in _raw \
                else _raw if isinstance(_raw, list) else []
        child_ids: list[int] = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and "task_id" in it:
                child_ids.append(int(it["task_id"]))
            elif isinstance(it, int):
                child_ids.append(it)
        children: list[TaskGenerator] = []
        for cid in child_ids:
            if not _registry.has(cid):
                continue
            cpart = _repo.get_partition(cid)
            child = _registry.get(cid, cpart.generation_params if cpart else {})
            children.append(child)
        if not children:
            raise RuntimeError(
                f"Группа {_name!r} (#{_pid}): не удалось собрать детей."
            )
        return GroupGenerator(name=_name, children=children, partition_id=_pid)

    registry.register_factory(part.id, factory)


def _register_test(registry: GeneratorRegistry, repo: Repository, part) -> None:
    raw = part.generation_params

    def factory(_params: dict, _registry=registry, _repo=repo,
                _pid=part.id, _name=part.name, _raw=raw):
        items = _raw.get("data") if isinstance(_raw, dict) and "data" in _raw \
                else _raw if isinstance(_raw, list) else []

        pairs = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            task_id = it.get("task_id")
            raw_count = it.get("task_cnt", it.get("count", 1))
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                count = 1
            if count <= 0:
                continue
            if task_id is None or not _registry.has(int(task_id)):
                continue
            cpart = _repo.get_partition(int(task_id))
            child = _registry.get(int(task_id),
                                  cpart.generation_params if cpart else {})
            if Capability.GROUPABLE not in child.capabilities:
                continue
            pairs.append((child, count))

        if not pairs:
            raise RuntimeError(
                f"Тест {_name!r} (#{_pid}): не удалось собрать заданий."
            )
        return TestGenerator(name=_name, items=pairs, partition_id=_pid)

    registry.register_factory(part.id, factory)
