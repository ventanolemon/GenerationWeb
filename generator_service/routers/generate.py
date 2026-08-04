"""
POST /generate — главный эндпоинт сервиса.

Логика проста благодаря тому, что вся сериализация живёт в самих
блоках и задачах (Block.to_dict, StaticTask.to_dict, TurnResult.to_dict).
Никаких isinstance-каскадов и знаний о типах блоков.

Поведение по типу задачи:
  StaticTask      → возвращаем task.to_dict() и добавляем partition_id
                    в meta, чтобы фронт мог пересоздать задание без
                    повторного выбора раздела.
  InteractiveTask → создаём сессию в session_store, возвращаем
                    session_id + initial_prompt. Дальнейшие ходы —
                    через POST /interactive/submit.
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import InteractiveTask, StaticTask, session_from_task
from core.scenarios import (IMPLEMENTED_MODES, MAX_ATTEMPTS, Layer, Scenario,
                            SessionMode)
from ..context import current_user_id as current_user_id_var

router = APIRouter(prefix="/generate", tags=["generate"])


class GenerateRequest(BaseModel):
    partition_id: int = Field(..., gt=0, description="ID раздела из Partitions")
    user_id: Optional[str] = Field(None, description="ID пользователя (login или guest UUID)")
    interactive: bool = Field(
        False,
        description=(
            "Открыть сессию с автопроверкой, если у задания есть "
            "спецификация ответа. По умолчанию выключено: прикрепление "
            "спецификации к генератору не должно менять поведение уже "
            "работающих вызовов."))
    session_mode: str = Field(
        "practice_free",
        description=(
            "Режим прохождения. Определяет контракт о записи попытки: "
            "practice_free попыток не пишет, practice пишет и считает. "
            "homework и exam описаны в модели, но пока не открыты."))
    max_attempts: Optional[int] = Field(
        None, ge=1, le=10,
        description=(
            "Попыток на вопрос. Пусто — берётся умолчание режима. "
            "Слой выдачи может это значение запереть."))


def _scenario_from(body: "GenerateRequest") -> Scenario:
    """
    Собрать сценарий из запроса.

    Неизвестный или ещё не открытый режим отвергается ЯВНО. ДЗ и зачёт
    описаны в модели, но им нужна дисциплина выдачи, которой нет: срок,
    единственная попытка, недоступность условия после сдачи. Записать
    попытку с пометкой «зачёт», не обеспечив условий зачёта, значит
    получить статистику, про которую потом нельзя сказать, что она
    означает — а обнаружится это через семестр.

    Слоя выдачи здесь ещё нет: параметры приходят от вызывающего и
    ложатся на слой задания. Когда появится выдача, она наложится
    следующим слоем и сможет запирать.
    """
    try:
        mode = SessionMode(body.session_mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный режим прохождения: {body.session_mode!r}")

    if mode not in IMPLEMENTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=(f"Режим {mode.value!r} описан, но пока не открыт: "
                    f"ему нужна дисциплина выдачи. Доступны: "
                    f"{', '.join(sorted(m.value for m in IMPLEMENTED_MODES))}."))

    scenario = Scenario.for_mode(mode)
    if body.max_attempts is not None:
        scenario = scenario.with_layer(Layer.TASK,
                                       {MAX_ATTEMPTS: body.max_attempts})
    return scenario


@router.post("")
def generate_task(body: GenerateRequest, request: Request) -> dict:
    current_user_id_var.set(body.user_id)
    registry = request.app.state.registry
    repo = request.app.state.repo
    sessions = request.app.state.sessions

    if not registry.has(body.partition_id):
        raise HTTPException(
            status_code=404,
            detail=f"Generator not found for partition {body.partition_id}",
        )

    # Раздел нужен для generation_params (физ. конструктор, группа, тест)
    partition = repo.get_partition(body.partition_id)
    params = partition.generation_params if partition else {}

    try:
        generator = registry.get(body.partition_id, params)
        task = generator.generate()
    except Exception as e:
        # Доменный код может бросить что угодно: RuntimeError из физики
        # ("не удалось сгенерировать за N попыток"), ValueError из linal
        # и т.п. Прокидываем как 500 с деталью.
        raise HTTPException(
            status_code=500,
            detail=f"Generator {generator.name if 'generator' in dir() else body.partition_id} failed: {e}",
        )

    if isinstance(task, StaticTask) and body.interactive and task.is_checkable:
        # Общая сессия над статическим заданием: генератор не писал ни
        # цикла, ни подкласса — он только приложил спецификацию ответа.
        scenario = _scenario_from(body)
        session = session_from_task(task, scenario=scenario)
        session_id = sessions.create(session, body.partition_id, body.user_id)
        return {
            "type": "interactive",
            "session_id": session_id,
            "partition_id": body.partition_id,
            "prompt": [b.to_dict() for b in session.initial_prompt()],
            "is_finished": session.is_finished(),
            "supports_tolerant": False,
            "widget": session.questions[0].widget_name(),
            "scenario": scenario.to_dict(),
        }

    if isinstance(task, StaticTask):
        result = task.to_dict()
        # Фронту удобнее иметь partition_id на верхнем уровне ответа,
        # а не только в meta — это явный контракт.
        result["partition_id"] = body.partition_id
        # Гарантируем, что в meta тоже лежит (для совместимости с десктопом)
        result.setdefault("meta", {})
        result["meta"].setdefault("partition_id", body.partition_id)
        return result

    if isinstance(task, InteractiveTask):
        # user_id уезжает в сессию: по нему её воскресит другой процесс с
        # той же межсессионной статистикой (см. SessionStore).
        session_id = sessions.create(task, body.partition_id, body.user_id)
        initial = task.initial_prompt()
        return {
            "type": "interactive",
            "session_id": session_id,
            "partition_id": body.partition_id,
            "prompt": [b.to_dict() for b in initial],
            "is_finished": task.is_finished(),
            "supports_tolerant": hasattr(task, "tolerant"),
        }

    raise HTTPException(
        status_code=500,
        detail=f"Unknown task type: {type(task).__name__}",
    )
