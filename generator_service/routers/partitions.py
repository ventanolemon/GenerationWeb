"""
CRUD для разделов (Partitions).

POST   /partitions           — создать или обновить (upsert)   [teacher/admin]
DELETE /partitions/{id}      — удалить                          [teacher/admin]
GET    /partitions/{id}      — получить с generation_params (для редактирования)
GET    /partitions/candidates/{subject_id}  — кандидаты для GroupEditor/TestEditor

## Запись авторизуется тем же правилом, что и push синхронизации

К таблице разделов ведут два пути записи — синк и этот CRUD, — и правило
«кому можно» у них одно (`core/content_authz.py`): нужна идентичность,
роль `teacher`/`admin`, и чужой предмет преподавателю недоступен на запись,
каким бы ни был набор выдач. Выдача даёт право видеть, а не переписывать.

Раньше правило было только у синка, а здесь не проверялось ничего: любой,
кто дотянулся до сервиса, мог переписать или снести чужой раздел, послав
запрос мимо синка. Так дыры и заводятся — правило пишут там, где о нём
подумали, а второй вход добавляют позже.

Идентичность приходит заголовками `X-User-Id` / `X-User-Role`, как во всём
внутреннем API; `web_layer` их пробрасывает. Сервис здесь авторитетен:
релей может их не прислать, и тогда ответ 401, а не «ну ладно».

> Чтение (`GET /partitions/{id}`, `/candidates/…`) НЕ авторизовано и этой
> правкой не тронуто — сознательно, чтобы не смешивать закрытие дыры на
> запись с отдельным решением про область видимости чтения. Это заметная
> щель: `generation_params` — весь авторский граф раздела, и сейчас он
> читается по id кем угодно, кто дотянулся до сервиса. Закрывать её надо
> тем же скоупом выдач, что и pull синка (`sync_api.visible_scope`).
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from bootstrap import build_registry
from const import WORDS_DIR
from core import content_authz
from ..context import current_user_id as current_user_id_var

router = APIRouter(prefix="/partitions", tags=["partitions"])


def _require_write(request: Request, subject_ids, x_user_id: Optional[str],
                   x_user_role: Optional[str]) -> None:
    """Пропустить или отказать 401/403. Правило — общее с синком."""
    refusal = content_authz.check_subject_write(
        request.app.state.repo, subject_ids,
        (x_user_id or "").strip() or None,
        (x_user_role or "").strip().lower() or "student")
    if refusal is not None:
        status, reason = refusal
        raise HTTPException(status_code=status, detail=reason)


class UpsertPartitionRequest(BaseModel):
    subject_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    constracted: int = Field(..., ge=0, le=4)  # 4 = граф (constracted=4)
    generation_params: Any = Field(default_factory=dict)


def _rebuild(request: Request) -> None:
    repo = request.app.state.repo
    stats_store = getattr(request.app.state, "stats_store", None)
    request.app.state.registry = build_registry(
        repo, WORDS_DIR,
        stats_store=stats_store,
        user_id_provider=lambda: current_user_id_var.get(),
    )


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
        raise HTTPException(status_code=404,
                            detail=f"Partition {partition_id} not found")
    d = part.to_dict()
    d["generation_params"] = part.generation_params
    return d


@router.post("")
def upsert_partition(
    body: UpsertPartitionRequest,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict:
    """
    Upsert совпадает по (subject_id, name), то есть перенести раздел в
    другой предмет им нельзя — предмет всегда ровно один, целевой. Поэтому
    и проверяется он один, в отличие от синка, где перенос возможен и
    проверяются оба.
    """
    _require_write(request, [body.subject_id], x_user_id, x_user_role)
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
def delete_partition(
    partition_id: int,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict:
    """
    Порядок проверок: сперва идентичность и роль (их видно, не читая базу),
    затем существование, затем владелец. Предмет раздела известен только
    из строки, поэтому проверка владельца обязана идти после 404 — иначе
    проверять было бы нечего.
    """
    _require_write(request, [], x_user_id, x_user_role)
    repo = request.app.state.repo
    part = repo.get_partition(partition_id)
    if part is None:
        raise HTTPException(status_code=404,
                            detail=f"Partition {partition_id} not found")
    _require_write(request, [part.subject_id], x_user_id, x_user_role)
    repo.delete_partition(partition_id)
    _rebuild(request)
    return {"deleted": partition_id}
