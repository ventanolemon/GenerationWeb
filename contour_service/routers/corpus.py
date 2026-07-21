"""
API куратора корпуса обучающих примеров (training_plan.md §1).

  GET   /corpus                     — список обучающих записей + сводка
  GET   /corpus/{id}                — полная запись + курация
  PATCH /corpus/{id}/curation       — разметить (gold / excluded / auto) + коммент

RBAC живёт в web_layer; сюда личность приходит X-User-Id / X-User-Role.
Курация — admin-only инструментарий (готовит выборку под дообучение): роль
проверяем здесь дополнительно к web_layer (defence in depth), 403 иначе.
Записи корпуса неизменяемы — меняется только оверлей corpus_curation.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..context import Identity, require_identity
from ..corpus import CorpusStore

router = APIRouter(prefix="/corpus", tags=["corpus"])


class CurationRequest(BaseModel):
    curation: str = Field(..., pattern="^(auto|gold|excluded)$")
    comment: str = Field(default="", max_length=2000)


def _corpus(request: Request) -> CorpusStore:
    return request.app.state.contour_corpus


def _require_admin(ident: Identity) -> None:
    if ident.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Куратор корпуса доступен только администратору.")


@router.get("")
def list_corpus(
    request: Request,
    curation: Optional[str] = None,
    kind: Optional[str] = None,
    ident: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _require_admin(ident)
    store = _corpus(request)
    kinds = (kind,) if kind in CorpusStore.TRAINING_KINDS else None
    listing = store.list_curated(curation=curation, kinds=kinds)
    return {**listing, "summary": store.curation_summary()}


@router.get("/{record_id}")
def get_corpus_record(
    record_id: str, request: Request,
    ident: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _require_admin(ident)
    rec = _corpus(request).get_curated(record_id)
    if rec is None:
        raise HTTPException(status_code=404,
                            detail=f"Запись {record_id} не найдена.")
    return rec


@router.patch("/{record_id}/curation")
def patch_curation(
    record_id: str, body: CurationRequest, request: Request,
    ident: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _require_admin(ident)
    ok = _corpus(request).set_curation(
        record_id, body.curation, comment=body.comment, curator=ident.user_id)
    if not ok:
        raise HTTPException(status_code=404,
                            detail=f"Запись {record_id} не найдена.")
    return {"record_id": record_id, "curation": body.curation}
