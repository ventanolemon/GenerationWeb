"""
Домашки: выдача заданий группам и просмотр студентом.

  POST   /assignments                 {partition_id, group_id, due_at?}  (teacher/admin)
  GET    /assignments/teaching        выдачи текущего преподавателя
  GET    /assignments/mine            домашки студента (по его группам)
  DELETE /assignments/{id}            снять выдачу (автор или admin)

Логика — core/assignments_api.py (headless). Идентичность обязательна (401
без X-User-Id); create/delete гейтятся ролью в самой логике (teacher/admin);
доменные ошибки (AssignmentActionError) → 400.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import assignments_api

from ..identity import CurrentUser

router = APIRouter(prefix="/assignments", tags=["assignments"])


class CreateAssignmentRequest(BaseModel):
    partition_id: int = Field(..., gt=0)
    group_id: int = Field(..., gt=0)
    due_at: Optional[float] = None



def _guard(fn):
    try:
        return fn()
    except assignments_api.AssignmentActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
def create_assignment(
    body: CreateAssignmentRequest,
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    uid, role = who.login, who.role
    return _guard(lambda: assignments_api.create(
        request.app.state.repo, actor_login=uid, role=role,
        partition_id=body.partition_id, group_id=body.group_id,
        due_at=body.due_at))


@router.get("/teaching")
def teaching(
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    uid = who.login
    return {"assignments": assignments_api.list_teaching(
        request.app.state.repo, actor_login=uid)}


@router.get("/{assignment_id}/progress")
def progress(
    assignment_id: int,
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    uid, role = who.login, who.role
    return _guard(lambda: assignments_api.progress(
        request.app.state.repo, actor_login=uid, role=role,
        assignment_id=assignment_id))


@router.get("/mine")
def mine(
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    uid = who.login
    return {"assignments": assignments_api.list_mine(
        request.app.state.repo, actor_login=uid)}


@router.delete("/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    request: Request,
    who: CurrentUser,
) -> dict[str, Any]:
    uid, role = who.login, who.role
    return _guard(lambda: assignments_api.delete(
        request.app.state.repo, actor_login=uid, role=role,
        assignment_id=assignment_id))
