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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/interactive", tags=["interactive"])


class SubmitRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_input: str = Field(..., description="Ответ пользователя; может быть пустой строкой")


@router.post("/submit")
def submit_answer(body: SubmitRequest, request: Request) -> dict:
    sessions = request.app.state.sessions
    task = sessions.get(body.session_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired",
        )

    try:
        result = task.submit(body.user_input)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"submit() failed: {e}",
        )

    response = result.to_dict()
    if response["next_prompt"] is None:
        # Сессия завершена — освобождаем место в сторе сразу,
        # не дожидаясь TTL.
        sessions.remove(body.session_id)
    return response


@router.get("/stats")
def session_stats(request: Request) -> dict:
    """Диагностика: сколько живых сессий и какой им возраст. Удобно
    при отладке утечек."""
    return request.app.state.sessions.stats()
