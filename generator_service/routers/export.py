"""
POST /export — экспорт заданий в .docx.

Возвращает бинарный StreamingResponse — ASP.NET Core потом пробросит
его в Results.File для скачивания браузером.

Под капотом — ровно тот же стек, что и в десктопе: docx.Document
плюс block.render_docx(). Это работает в headless-окружении:
  - python-docx чистый Python без Qt;
  - matplotlib используется для рендера формул (через latex_to_png_bytes),
    у него уже стоит backend "Agg" в core/rendering.py;
  - ImageBlock.render_docx использует PIL и BytesIO.

Экспорт идёт только для StaticTask. Если генератор интерактивный,
возвращаем 400 — фронт должен это знать заранее по флагу capabilities
у раздела (этим займётся ASP.NET-слой) и не показывать кнопку.
"""

from __future__ import annotations
from io import BytesIO

from docx import Document
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from typing import Optional

from core import StaticTask, export_api

router = APIRouter(prefix="/export", tags=["export"])


class ExportRequest(BaseModel):
    partition_id: int = Field(..., gt=0)
    count: int = Field(1, ge=1, le=50,
                       description="Заданий в одном варианте")
    variants: int = Field(1, ge=1, le=50,
                          description="Сколько вариантов собрать")
    answers: Optional[str] = Field(
        None,
        description="under | variant_end | file_end | hidden")
    # Старый контракт: его шлют три экрана фронта и десктоп. true —
    # «под заданием», false — «скрыть».
    with_answers: Optional[bool] = Field(True)


@router.post("")
def export_tasks(body: ExportRequest, request: Request):
    registry = request.app.state.registry
    repo = request.app.state.repo

    if not registry.has(body.partition_id):
        raise HTTPException(
            status_code=404,
            detail=f"Generator not found for partition {body.partition_id}",
        )

    partition = repo.get_partition(body.partition_id)
    params = partition.generation_params if partition else {}
    generator = registry.get(body.partition_id, params)

    try:
        placement = export_api.normalise_placement(body.answers,
                                                   body.with_answers)
    except export_api.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    variants = []
    for _ in range(body.variants):
        tasks = []
        for _ in range(body.count):
            task = generator.generate()
            if not isinstance(task, StaticTask):
                raise HTTPException(
                    status_code=400,
                    detail="Export is only available for static tasks",
                )
            tasks.append(task)
        variants.append(tasks)

    doc = Document()
    title = partition.name if partition else "Задания"
    try:
        export_api.build_document(doc, variants, title=title,
                                  answers=placement)
    except export_api.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    filename = f"tasks_{body.partition_id}.docx"
    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
