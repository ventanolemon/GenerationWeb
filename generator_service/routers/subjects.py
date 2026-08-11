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

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import Capability, subjects_api

from .. import identity
from ..identity import CurrentUser, MaybeUser

router = APIRouter(prefix="/subjects", tags=["subjects"])


class SubjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_name: str = Field(default="", max_length=200)


def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except subjects_api.SubjectActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_subjects(request: Request, who: MaybeUser) -> list[dict]:
    """
    Витрина предметов. РАНЬШЕ отдавала все подряд — после §8 это означало,
    что преподаватель одной организации видит предметы соседней. Скоуп
    здесь тот же, что у синка и аналитики: два разных ответа на вопрос
    «что мне видно» разъезжаются.
    """
    repo = request.app.state.repo
    actor, role = identity.actor(who)
    visible = subjects_api.visible(repo, actor=actor, role=role)["subjects"]
    allowed = {row["id"] for row in visible}
    return [s.to_dict() for s in repo.list_subjects() if s.id in allowed]


@router.get("/manage")
def list_for_management(request: Request, who: CurrentUser) -> dict[str, Any]:
    """То же, но с владельцем и числом разделов — данные редактора."""
    return subjects_api.visible(request.app.state.repo,
                                actor=who.login, role=who.role)


@router.post("")
def create_subject(body: SubjectRequest, request: Request,
                   who: CurrentUser) -> dict[str, Any]:
    return _run(subjects_api.create, request.app.state.repo,
                name=body.name, parent_name=body.parent_name,
                actor=who.login, role=who.role,
                organization_id=who.organization_id)


@router.patch("/{subject_id}")
def rename_subject(subject_id: int, body: SubjectRequest, request: Request,
                   who: CurrentUser) -> dict[str, Any]:
    return _run(subjects_api.rename, request.app.state.repo,
                subject_id=subject_id, name=body.name, actor=who.login,
                role=who.role, organization_id=who.organization_id)


@router.delete("/{subject_id}")
def delete_subject(subject_id: int, request: Request,
                   who: CurrentUser) -> dict[str, Any]:
    return _run(subjects_api.delete, request.app.state.repo,
                subject_id=subject_id, actor=who.login, role=who.role,
                organization_id=who.organization_id)


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
        is_checkable = False
        if registry.has(p.id):
            try:
                gen = registry.get(p.id, p.generation_params)
                # Два РАЗНЫХ вопроса, и слить их в один нельзя.
                #
                # is_interactive — «можно ли здесь отвечать»: и сессия
                # генератора, и общая машинка над спецификацией.
                # is_checkable — «есть ли у задания статическая форма
                # ПОМИМО сессии».
                #
                # Разница видна на физике. Её задача проверяема, но она
                # остаётся обычным заданием: преподаватель генерирует
                # варианты и выгружает их в Word. Отдав витрине один флаг,
                # мы увели бы весь предмет на экран тренажёра и отняли
                # экспорт. У тренажёра слов, наоборот, статической формы
                # нет вовсе — только сессия.
                is_interactive = bool(
                    gen.capabilities & (Capability.INTERACTIVE
                                        | Capability.CHECKABLE))
                is_checkable = bool(gen.capabilities & Capability.CHECKABLE)
            except Exception:
                # Если фабрика для группы/теста не смогла собрать детей
                # (например, после удаления одного из дочерних разделов),
                # она бросит RuntimeError. Это не интерактив, точно.
                is_interactive = False
                is_checkable = False
        d["is_interactive"] = is_interactive
        d["is_checkable"] = is_checkable
        result.append(d)
    return result
