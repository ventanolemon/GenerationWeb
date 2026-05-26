"""
CRUD для разделов (Partitions).

POST   /partitions           — создать или обновить (upsert)
DELETE /partitions/{id}      — удалить
GET    /partitions/{id}      — получить с generation_params (для редактирования)
GET    /partitions/candidates/{subject_id}  — кандидаты для GroupEditor/TestEditor
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from bootstrap import build_registry
from const import WORDS_DIR

router = APIRouter(prefix="/partitions", tags=["partitions"])


class UpsertPartitionRequest(BaseModel):
    subject_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    constracted: int = Field(..., ge=0, le=3)
    generation_params: Any = Field(default_factory=dict)


def _rebuild(request: Request) -> None:
    repo = request.app.state.repo
    request.app.state.registry = build_registry(repo, WORDS_DIR)


@router.get("/candidates/{subject_id}")
def get_candidates(subject_id: int, request: Request) -> dict:
    """Возвращает разделы своего предмета + разделы «дочерних» предметов
    (тех, у кого parent_name == имя нашего предмета).
    Используется редакторами группы и теста для выбора дочерних заданий."""
    repo = request.app.state.repo
    own = repo.list_partitions_for_subject(subject_id)
    all_subjects = repo.list_subjects()
    my_subject = next((s for s in all_subjects if s.id == subject_id), None)

    sibling_parts = []
    if my_subject:
        for s in all_subjects:
            if s.id != subject_id and s.parent_name == my_subject.name:
                sibling_parts.extend(repo.list_partitions_for_subject(s.id))

    return {
        "own": [p.to_dict() for p in own],
        "siblings": [p.to_dict() for p in sibling_parts],
    }


@router.get("/{partition_id}")
def get_partition(partition_id: int, request: Request) -> dict:
    repo = request.app.state.repo
    part = repo.get_partition(partition_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Partition {partition_id} not found")
    d = part.to_dict()
    d["generation_params"] = part.generation_params
    return d


@router.post("")
def upsert_partition(body: UpsertPartitionRequest, request: Request) -> dict:
    repo = request.app.state.repo
    pid = repo.upsert_partition(
        subject_id=body.subject_id,
        name=body.name,
        constracted=body.constracted,
        generation_params=body.generation_params,
    )
    _rebuild(request)
    return {"partition_id": pid}


@router.delete("/{partition_id}")
def delete_partition(partition_id: int, request: Request) -> dict:
    repo = request.app.state.repo
    part = repo.get_partition(partition_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Partition {partition_id} not found")
    repo.delete_partition(partition_id)
    _rebuild(request)
    return {"deleted": partition_id}
