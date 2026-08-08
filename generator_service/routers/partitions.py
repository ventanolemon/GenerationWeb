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

## Чтение авторского содержимого — своё правило, тот же скоуп

`GET /partitions/{id}` отдаёт `generation_params`: сам граф или конфиг
генератора. Раньше он читался по id кем угодно, кто дотянулся до сервиса, —
то есть авторская работа преподавателя лежала открытой.

Правило (`content_authz.check_authoring_read`) мягче права на запись по
владельцу и строже по роли. Выданный чужой предмет читать МОЖНО: выдача
ровно для этого и нужна, и pull синка такому преподавателю этот граф уже
присылает — запрет здесь развёл бы веб и синк. А роль нужна teacher/admin:
`generation_params` — «кишки» задания, решающему они не нужны (веб ничего
не генерирует локально, задание собирает сервер), зато помогают угадывать
ответы.

Витрина (`GET /subjects`, `GET /subjects/{id}/partitions`) НЕ тронута: она
отдаёт имена и виды разделов, а не их устройство, и по ней ходит в том
числе гость, решающий задачи. Закрывать её — отдельное продуктовое решение
про доступ гостя к каталогу, а не про эту дыру.

Чужое отвечает **404**, а не 403: иначе перебором последовательных id
выясняется, какие разделы существуют у коллег.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from bootstrap import build_registry
from const import WORDS_DIR
from core import content_authz

from .. import identity
from ..identity import Identity, MaybeUser
from ..context import current_user_id as current_user_id_var

router = APIRouter(prefix="/partitions", tags=["partitions"])



def _refuse(refusal) -> None:
    if refusal is not None:
        status, reason = refusal
        raise HTTPException(status_code=status, detail=reason)


def _require_write(request: Request, subject_ids,
                   who: Optional[Identity]) -> None:
    """Пропустить или отказать 401/403. Правило — общее с синком."""
    actor, role = identity.actor(who)
    _refuse(content_authz.check_subject_write(
        request.app.state.repo, subject_ids, actor, role))


def _require_read(request: Request, subject_ids,
                  who: Optional[Identity]) -> None:
    """Пропустить или отказать 401/403/404 на чтение авторского содержимого."""
    actor, role = identity.actor(who)
    _refuse(content_authz.check_authoring_read(
        request.app.state.repo, subject_ids, actor, role))


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
def get_candidates(
    subject_id: int,
    request: Request,
    who: MaybeUser,
) -> dict:
    """
    Разделы своего предмета + разделы «дочерних» (тех, у кого parent_name ==
    имя нашего). Редакторы группы и теста выбирают отсюда дочерние задания.

    Соседние предметы ФИЛЬТРУЮТСЯ по скоупу чтения, и это не то же самое,
    что проверить запрошенный предмет. Иначе проверку обходят с другой
    стороны: не «покажи мне чужой раздел», а «покажи список, в котором он
    окажется». Свой предмет проверяется отказом, чужие соседи — молча
    выпадают: их отсутствие и есть правильный ответ, а не ошибка.
    """
    _require_read(request, [subject_id], who)
    actor, role = identity.actor(who)
    repo = request.app.state.repo
    readable = content_authz.readable_subject_ids(repo, actor, role)

    own = repo.list_partitions_for_subject(subject_id)
    all_subjects = repo.list_subjects()
    my_subject = next((s for s in all_subjects if s.id == subject_id), None)

    sibling_parts = []
    if my_subject:
        for s in all_subjects:
            if s.id == subject_id or s.parent_name != my_subject.name:
                continue
            if readable is not None and s.id not in readable:
                continue
            sibling_parts.extend(repo.list_partitions_for_subject(s.id))

    return {
        "own": [p.to_dict() for p in own],
        "siblings": [p.to_dict() for p in sibling_parts],
    }


@router.get("/{partition_id}")
def get_partition(
    partition_id: int,
    request: Request,
    who: MaybeUser,
) -> dict:
    """
    Раздел вместе с `generation_params` — то есть с его устройством. Это
    эндпоинт РЕДАКТОРА, а не витрины, и авторизуется соответственно.

    Порядок: идентичность и роль (видно, не читая базу) → существование →
    скоуп. Предмет раздела известен только из строки, поэтому проверка
    скоупа обязана идти после чтения; наружу оба исхода выглядят одинаково
    — 404, чтобы перебор id ничего не рассказывал.
    """
    _require_read(request, [], who)
    repo = request.app.state.repo
    part = repo.get_partition(partition_id)
    if part is None:
        # Тот же текст, что у отказа по скоупу (content_authz.NOT_FOUND).
        # Разные формулировки на одном статусе сводили бы всю затею на нет:
        # перебор различал бы «нет такого» и «есть, но не ваш» по сообщению.
        raise HTTPException(status_code=404, detail="Раздел не найден.")
    _require_read(request, [part.subject_id], who)
    d = part.to_dict()
    d["generation_params"] = part.generation_params
    return d


@router.post("")
def upsert_partition(
    body: UpsertPartitionRequest,
    request: Request,
    who: MaybeUser,
) -> dict:
    """
    Upsert совпадает по (subject_id, name), то есть перенести раздел в
    другой предмет им нельзя — предмет всегда ровно один, целевой. Поэтому
    и проверяется он один, в отличие от синка, где перенос возможен и
    проверяются оба.
    """
    _require_write(request, [body.subject_id], who)
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
    who: MaybeUser,
) -> dict:
    """
    Порядок проверок: сперва идентичность и роль (их видно, не читая базу),
    затем существование, затем владелец. Предмет раздела известен только
    из строки, поэтому проверка владельца обязана идти после 404 — иначе
    проверять было бы нечего.
    """
    _require_write(request, [], who)
    repo = request.app.state.repo
    part = repo.get_partition(partition_id)
    if part is None:
        raise HTTPException(status_code=404,
                            detail=f"Partition {partition_id} not found")
    _require_write(request, [part.subject_id], who)
    repo.delete_partition(partition_id)
    _rebuild(request)
    return {"deleted": partition_id}
