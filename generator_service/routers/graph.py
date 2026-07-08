"""
Graph-роутер: каталог узлов, валидация, предпросмотр графа.

Тонкая HTTP-обёртка над core.graph_api (там вся логика, headless и
переиспользуемая контуром). Контракт — docs/architecture/
graph_editor_api_contract.md §2. Все три операции детерминированы (это НЕ
контур, LLM здесь нет), поэтому живут в generator_service, где импортирован
core/graph.

  GET  /graph/catalog          — палитра/заземление (узлы, типы, конверсии)
  POST /graph/validate {graph} — сборка GraphExecutor, дословные ошибки
  POST /graph/preview  {graph, seeds?} — блоки условия/ответа (BlockJSON)
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core import graph_api

router = APIRouter(prefix="/graph", tags=["graph"])


class ValidateRequest(BaseModel):
    graph: dict


class PreviewRequest(BaseModel):
    graph: dict
    seeds: Optional[list[int]] = Field(default=None)


@router.get("/catalog")
def get_catalog() -> dict:
    """Каталог узлов для палитры редактора и заземления контура."""
    return graph_api.build_catalog()


@router.post("/validate")
def validate(body: ValidateRequest) -> dict:
    """Проверить граф (структура + типы портов). Ошибки — дословный текст
    GraphValidationError (называет узлы по id)."""
    return graph_api.validate_graph(body.graph)


@router.post("/preview")
def preview(body: PreviewRequest) -> dict:
    """Исполнить граф на нескольких seed и вернуть блоки условия/ответа
    (BlockJSON) — их рендерит существующий frontend BlockRenderer."""
    return graph_api.preview_graph(body.graph, body.seeds)
