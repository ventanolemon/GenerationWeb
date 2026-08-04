"""
POST /interactive/submit — отправка ответа в активной сессии.

Формат запроса:  { "session_id": "...", "user_input": "..." }
Формат ответа:   {
                   "correct": bool,
                   "feedback": [<block>],
                   "next_prompt": [<block>] | null,
                   "is_finished": bool
                 }

Это ровно TurnResult.to_dict() — никаких дополнительных полей.
Когда сессия завершается (next_prompt == null), удаляем её из стора
сразу, чтобы не висела до TTL.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interactive", tags=["interactive"])


class SubmitRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_input: str = Field(..., description="Ответ пользователя; может быть пустой строкой")
    tolerant: bool = Field(False, description="Принимать мелкие опечатки (расстояние Левенштейна)")


@router.post("/submit")
def submit_answer(body: SubmitRequest, request: Request) -> dict:
    sessions = request.app.state.sessions
    task = sessions.get(body.session_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired",
        )

    if hasattr(task, "tolerant"):
        task.tolerant = body.tolerant

    try:
        result = task.submit(body.user_input)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"submit() failed: {e}",
        )

    _record_attempts(request, body.session_id, task)

    response = result.to_dict()
    if response["next_prompt"] is None:
        # Сессия завершена — освобождаем место в сторе сразу,
        # не дожидаясь TTL.
        sessions.remove(body.session_id)
    else:
        # Снимок после КАЖДОГО хода: отстань он на ход, переезд сессии в
        # другой процесс вернул бы пользователя к предыдущему слову.
        sessions.save(body.session_id)
    return response


def _record_attempts(request: Request, session_id: str, task) -> None:
    """
    Записать попытки по закрытым вопросам, если сценарий это предписывает.

    Зовётся после КАЖДОГО хода, а не только на завершении сессии. Сессию
    бросают чаще, чем доводят до конца, и запись «в конце» потеряла бы
    всё, на что студент успел ответить. Ключ попытки детерминирован, так
    что повторная запись тех же вопросов ничего не удваивает.

    Ошибка записи не роняет ход. Телеметрия — улучшение, а не условие
    работы: уронить из-за неё ответ студента было бы обменом ценного на
    дешёвое.
    """
    scenario = getattr(task, "scenario", None)
    if scenario is None or not scenario.contract.records_attempts:
        return
    if not getattr(task, "outcomes", None):
        return

    sessions = request.app.state.sessions
    context = sessions.context(session_id)
    repo = getattr(request.app.state, "repo", None)
    if context is None or repo is None:
        return
    partition_id, user_id = context

    try:
        from core.attempts import attempts_from_session
        repo.save_attempts(attempts_from_session(
            task, scenario,
            session_id=session_id,
            user_id=user_id or "",
            partition_id=partition_id,
        ))
    except Exception:
        logger.exception("не удалось записать попытки сессии %s", session_id)


@router.get("/stats")
def session_stats(request: Request) -> dict:
    """Диагностика: сколько живых сессий и какой им возраст. Удобно
    при отладке утечек."""
    return request.app.state.sessions.stats()
