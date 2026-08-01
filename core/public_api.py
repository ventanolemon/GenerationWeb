"""
Публичный контракт: каталог и разрешение публичных идентификаторов.

Этап 3 из docs/architecture/public_api.md. Смысл модуля — НЕ отдавать
наружу внутреннюю схему. Внутри раздел это `Partitions.id` и число
`constracted`; снаружи — «тема» со стабильным `id` и словарным `kind`.
Развязка нужна ровно потому, что обещание совместимости даётся на публичные
имена: перенумеруется таблица или появится шестой тип раздела — внешний
контракт не шелохнётся.

Словарь `kind` — часть контракта, значения не переименовываются. Число
`constracted` наружу не уходит вовсе: у него нет смысла за пределами нашей
БД, а поддерживать его историю пришлось бы вечно.

Терминология тоже переведена: внутренние «предмет/раздел» снаружи —
`subject`/`topic`. «Partition» — деталь реализации, слово из схемы, и в
публичном API ему делать нечего.
"""

from __future__ import annotations

from typing import Optional

from . import api_clients
from .repository import Repository

# constracted → публичный kind. Значения стабильны: их читают машины.
KIND_BY_CONSTRACTED = {
    0: "single",        # одиночное задание
    1: "constructor",   # конструктор (физика)
    2: "group",         # группа заданий
    3: "test",          # тест с вариантами
    4: "graph",         # граф-задание
}
DEFAULT_KIND = "single"


class PublicApiError(ValueError):
    """Ошибка запроса к публичному API — роутер превращает в 400/404."""


def kind_for(constracted: int) -> str:
    return KIND_BY_CONSTRACTED.get(constracted, DEFAULT_KIND)


def catalog(repo: Repository, client_id: int, *, registry=None) -> dict:
    """
    Что доступно этому ключу: предметы со своими темами.

    Тема попадает в каталог, только если для неё ЕСТЬ генератор: отдать
    интегратору тему, на которой `POST /tasks` гарантированно вернёт ошибку,
    значит соврать в каталоге. Без реестра (в тестах) фильтр не применяется.
    """
    allowed = set(api_clients.client_subject_ids(repo, client_id))
    subjects = []
    for subject in repo.list_subjects():
        if subject.id not in allowed:
            continue
        topics = []
        for part in repo.list_partitions_for_subject(subject.id):
            if registry is not None and not registry.has(part.id):
                continue
            topics.append({
                "id": repo.public_id("partition", part.id),
                "name": part.name,
                "kind": kind_for(part.constracted),
            })
        if not topics:
            continue        # предмет без доступных тем наружу не показываем
        subjects.append({
            "id": repo.public_id("subject", subject.id),
            "name": subject.name,
            "topics": topics,
        })
    return {"subjects": subjects}


def resolve_topic(repo: Repository, client_id: int, topic_id: str) -> int:
    """
    Публичный id темы → внутренний partition_id, с проверкой доступа.

    «Нет такой темы» и «тема есть, но не для этого ключа» отвечают
    ОДИНАКОВО. Иначе публичный API стал бы оракулом: перебором id можно было
    бы выяснить, какие темы существуют у других клиентов.
    """
    partition_id = repo.resolve_public_id("partition", (topic_id or "").strip())
    if partition_id is None:
        raise PublicApiError(f"Тема {topic_id!r} не найдена.")
    part = repo.get_partition(partition_id)
    if part is None:
        raise PublicApiError(f"Тема {topic_id!r} не найдена.")
    if part.subject_id not in set(api_clients.client_subject_ids(repo, client_id)):
        raise PublicApiError(f"Тема {topic_id!r} не найдена.")
    return partition_id


def task_payload(repo: Repository, partition_id: int, task_dict: dict) -> dict:
    """
    Ответ `POST /tasks` для статического задания.

    Внутренний `partition_id` из `meta` вычищается и заменяется публичным
    `topic_id`: meta задумана как служебные данные генератора, но наружу она
    уезжает целиком, и внутренние идентификаторы в ней — это та же утечка
    схемы, только с чёрного хода.
    """
    meta = dict(task_dict.get("meta") or {})
    meta.pop("partition_id", None)
    return {
        "type": "static",
        "topic_id": repo.public_id("partition", partition_id),
        "statement": task_dict.get("statement") or [],
        "answer": task_dict.get("answer") or [],
        "meta": meta,
    }


def interactive_payload(repo: Repository, partition_id: int, session_id: str,
                        prompt: list, *, supports_tolerant: bool) -> dict:
    return {
        "type": "interactive",
        "topic_id": repo.public_id("partition", partition_id),
        "session_id": session_id,
        "prompt": prompt,
        "supports_tolerant": supports_tolerant,
    }


def turn_payload(result: dict, session_id: str) -> dict:
    """Ответ на ход интерактивной сессии."""
    return {
        "type": "turn",
        "session_id": session_id,
        "correct": bool(result.get("correct")),
        "feedback": result.get("feedback") or [],
        "next_prompt": result.get("next_prompt"),
        "is_finished": bool(result.get("is_finished")),
    }


def me_payload(client: dict, usage: dict,
               subject_count: Optional[int] = None) -> dict:
    """`GET /v1/me` — чем полезен: интегратор видит остаток квоты, не
    дожидаясь 429, и убеждается, что ключ жив, не тратя генерацию."""
    out = {
        "client": client.get("client_name") or "",
        "key_prefix": client.get("prefix") or "",
        "kind": client.get("kind") or "server",
        "usage": usage,
    }
    if subject_count is not None:
        out["subjects_available"] = subject_count
    return out
