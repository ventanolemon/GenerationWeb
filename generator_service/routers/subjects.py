"""
GET /subjects                       — все предметы
GET /subjects/{subject_id}/partitions — разделы предмета

Subject и Partition уже умеют в to_dict() (см. core/repository.py), но
для разделов добавляем три специфичных для сервиса поля:
  has_generator — зарегистрирован ли модуль в реестре,
  view_kind     — single/table/test, подсказка фронту, как рендерить,
  is_interactive — стоит ли у генератора флаг INTERACTIVE
                   (нужно фронту, чтобы выбрать диалоговый view ещё ДО
                   первого /generate — без эвристик типа "если предмет
                   английский, то интерактив").

Эти поля не входят в Partition.to_dict() сознательно: они относятся
к рантайму сервиса, а не к самой сущности раздела в БД.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from core import Capability

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("")
def list_subjects(request: Request) -> list[dict]:
    repo = request.app.state.repo
    return [s.to_dict() for s in repo.list_subjects()]


@router.get("/{subject_id}/partitions")
def list_partitions(subject_id: int, request: Request) -> list[dict]:
    repo = request.app.state.repo
    registry = request.app.state.registry

    # Без проверки существования subject_id мы бы вернули пустой список —
    # это маскирует ошибки клиента (например, опечатку в id). 404 честнее.
    if not any(s.id == subject_id for s in repo.list_subjects()):
        raise HTTPException(status_code=404, detail=f"Subject {subject_id} not found")

    result = []
    for p in repo.list_partitions_for_subject(subject_id):
        d = p.to_dict()
        d["has_generator"] = registry.has(p.id)
        d["view_kind"] = repo.view_kind_for(p)

        # Узнаём capabilities, не создавая генератор: если он
        # зарегистрирован как готовый экземпляр — достаём флаги
        # напрямую. Если зарегистрирован как фабрика (группа, тест,
        # физ. конструктор), Capability.INTERACTIVE заведомо нет —
        # composite-генераторы по стандарту STATIC.
        is_interactive = False
        if registry.has(p.id):
            try:
                gen = registry.get(p.id, p.generation_params)
                is_interactive = Capability.INTERACTIVE in gen.capabilities
            except Exception:
                # Если фабрика для группы/теста не смогла собрать детей
                # (например, после удаления одного из дочерних разделов),
                # она бросит RuntimeError. Это не интерактив, точно.
                is_interactive = False
        d["is_interactive"] = is_interactive
        result.append(d)
    return result
