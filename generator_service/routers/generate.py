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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import InteractiveTask, StaticTask

router = APIRouter(prefix="/generate", tags=["generate"])


class GenerateRequest(BaseModel):
    partition_id: int = Field(..., gt=0, description="ID раздела из Partitions")


@router.post("")
def generate_task(body: GenerateRequest, request: Request) -> dict:
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
        session_id = sessions.create(task, body.partition_id)
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
