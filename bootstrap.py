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

    # Английские словари: 1000+i → раздел английского
    if words_dir.exists():
        for i, path in enumerate(sorted(words_dir.glob("*.json"))):
            pid = 1000 + i
            # Имя зависит от типа: для предложений — пометим как «(предложения)»
            display = _english_display_name(path)
            repo.ensure_code_partition(
                partition_id=pid,
                subject_id=2,
                name=display,
            )


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
        for i, path in enumerate(sorted(words_dir.glob("*.json"))):
            pid = 1000 + i
            display = _english_display_name(path)
            gen = english_generators_for_path(
                path, pid, name=display,
                stats_store=stats_store,
                user_id_provider=user_id_provider,
            )
            if gen is not None:
                registry.register(gen)

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
