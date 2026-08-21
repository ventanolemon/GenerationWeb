"""
База знаний: чтение правок и правка страниц.

  GET    /guide                     страницы с наложенными правками (всем)
  PUT    /guide/{page_id}           сохранить правку (админ, разработчик)
  DELETE /guide/{page_id}           вернуть к поставочной (админ, разработчик)

Почему чтение открыто ВСЕМ, включая гостя
------------------------------------------
База знаний открыта гостю намеренно: инструкция, которую видно только
после входа, не помогает тому, кто как раз и не понимает, как войти. Если
закрыть чтение правок, гость увидит поставочную страницу, а вошедший —
исправленную, и разойдутся они молча.

Отдельно важно, чем эта ручка НЕ является. Она не единственный источник
документации: клиент показывает вкомпилированный `content.json`, а сюда
ходит, чтобы наложить правки. Служба недоступна — читатель видит
поставочную версию, а не пустой экран. Это то самое свойство, ради
которого база знаний и вкомпилирована.

Логика — `core/guide_store.py` (headless), роутер адаптирует HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import guide_store

from ..identity import MaybeUser

router = APIRouter(prefix="/guide", tags=["guide"])


class PageBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., max_length=200_000)


@router.get("")
def read_guide(request: Request, who: MaybeUser = None) -> dict:
    """
    Страницы с наложенными правками.

    `can_edit` едет вместе с содержимым, а не отдельной ручкой: клиенту
    он нужен ровно тогда, когда он и так запрашивает страницы, а второй
    запрос — это второй способ разойтись с первым.
    """
    repo = request.app.state.repo
    actor = getattr(who, "login", None)
    role = getattr(who, "role", None)
    return {
        "pages": guide_store.merged(repo),
        "can_edit": guide_store.may_edit(repo, actor, role),
    }


@router.put("/{page_id}")
def save_page(page_id: str, body: PageBody, request: Request,
              who: MaybeUser = None) -> dict:
    repo = request.app.state.repo
    _require_editor(repo, who)
    try:
        return guide_store.save(repo, page_id, title=body.title,
                                body=body.body,
                                actor=getattr(who, "login", "") or "")
    except guide_store.GuideEditError as exc:
        # 400, а не 500: текст правки не подошёл по формату, и сообщение
        # об этом написано на языке автора страницы — его и показываем.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{page_id}")
def reset_page(page_id: str, request: Request,
               who: MaybeUser = None) -> dict:
    repo = request.app.state.repo
    _require_editor(repo, who)
    return {"reset": guide_store.reset(repo, page_id)}


def _require_editor(repo, who) -> None:
    try:
        guide_store.require_editor(repo, getattr(who, "login", None),
                                   getattr(who, "role", None))
    except guide_store.GuideAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
