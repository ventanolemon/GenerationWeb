"""
API джоб контура (contour_integration.md §2/§4).

  POST /contour/jobs                — создать джобу → 202 {job_id}
  GET  /contour/jobs/{id}           — статус/превью/флаги/вердикт (поллинг 2–5 с)
  GET  /contour/jobs                — список джоб пользователя
  POST /contour/jobs/{id}/approve   — S6: принять → партиция constracted=4
  POST /contour/jobs/{id}/reject    — S6: отклонить (причина в лог эскалаций)

RBAC живёт в web_layer; сюда личность приходит заголовками X-User-Id /
X-User-Role (system_topology §6 п.2) — здесь только владение: джобы
awaiting_human видит АВТОР и admin, чужие teacher не видит и не утверждает.

Инвариант №5 контракта: партиция создаётся ТОЛЬКО из approve (S6, человек),
никогда автоматически.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..context import Identity, require_identity
from ..corpus import CorpusStore
from ..providers import TASK_GENERATE
from ..queue import AWAITING_HUMAN, JobQueue, REJECTED

router = APIRouter(prefix="/contour", tags=["contour"])


class CreateJobRequest(BaseModel):
    description: str = Field(..., min_length=3)
    subject_id: int = Field(..., gt=0)
    constraints: Optional[dict] = None      # {"task_type": "static|interactive"}


class ApproveRequest(BaseModel):
    partition_name: str = Field(default="", description="Имя партиции; пусто = из описания")
    note: str = ""


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)


def _queue(request: Request) -> JobQueue:
    return request.app.state.contour_queue


def _corpus(request: Request) -> CorpusStore:
    return request.app.state.contour_corpus


def _visible_job(request: Request, job_id: str, ident: Identity) -> dict:
    job = _queue(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Джоба {job_id} не найдена.")
    if ident.role != "admin" and int(job["created_by"]) != ident.user_id:
        # Чужие джобы teacher не видит (contour_integration §4).
        raise HTTPException(status_code=404, detail=f"Джоба {job_id} не найдена.")
    return job


@router.post("/jobs", status_code=202)
def create_job(body: CreateJobRequest, request: Request,
               ident: Identity = Depends(require_identity)) -> dict:
    """Создать джобу (status=queued); воркер подхватит её из очереди."""
    if ident.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Запускать LLM-контур могут teacher и admin.")
    job_id = _queue(request).enqueue(
        created_by=ident.user_id, subject_id=body.subject_id,
        description=body.description.strip(),
        constraints=body.constraints or {},
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs")
def list_jobs(request: Request,
              ident: Identity = Depends(require_identity)) -> dict:
    """Джобы пользователя (admin — все): раздел «На утверждении» и история."""
    jobs = _queue(request).list_for_user(ident.user_id, ident.role)
    return {"jobs": [_job_summary(j) for j in jobs]}


def _job_summary(job: dict) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "subject_id": job["subject_id"],
        "description": job["description"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request,
            ident: Identity = Depends(require_identity)) -> dict:
    """Статус + данные экрана S6: превью заданий из probe (случайные seed),
    warn-флаги, summary/confidence критика, история раундов."""
    job = _visible_job(request, job_id, ident)
    probe = job.get("result_probe") or {}
    runs = [r for r in (probe.get("runs") or []) if r.get("error") is None]
    previews = [
        {"seed": r["seed"], "statement": r["statement"], "answer": r["answer"]}
        for r in runs[:5]
    ]
    return {
        **_job_summary(job),
        "error": job.get("error"),
        "previews": previews,                       # 3–5 заданий для человека
        "flags": (probe.get("flags") or []),        # warn-флаги SYM-проб
        "critic": job.get("critic"),
        "rounds": [
            {k: v for k, v in rnd.items() if k != "graph"}   # компактно
            for rnd in (job.get("rounds") or [])
        ],
        "result_graph": job.get("result_graph"),
    }


@router.post("/jobs/{job_id}/approve")
def approve_job(job_id: str, body: ApproveRequest, request: Request,
                ident: Identity = Depends(require_identity)) -> dict:
    """S6: принять. Партиция constracted=4 (владелец = автор джобы) +
    корпусная запись kind=generate с human.approved=true."""
    job = _visible_job(request, job_id, ident)
    if job["status"] != AWAITING_HUMAN:
        raise HTTPException(
            status_code=409,
            detail=f"Джоба в статусе {job['status']!r} — утверждать можно "
                   f"только awaiting_human.")
    graph = job.get("result_graph")
    probe = job.get("result_probe")
    if not graph or not probe:
        raise HTTPException(status_code=500,
                            detail="У джобы нет result_graph/probe.")

    # Партиция — через существующий Repository (единственный путь записи
    # партиций, тот же формат generation_params, что у граф-редактора).
    repo = request.app.state.repo
    name = body.partition_name.strip() or job["description"][:80]
    partition_id = repo.upsert_partition(
        subject_id=int(job["subject_id"]), name=name,
        constracted=4, generation_params=graph,
    )

    cfg = request.app.state.contour_config
    record_id = _corpus(request).write_generate(
        job_id, job["description"], job.get("constraints") or None,
        target_graph=graph, probe=probe, critic=job.get("critic"),
        catalog_version=(probe.get("catalog_version")
                         or _catalog_version()),
        engine_commit=cfg.engine_commit,
        model=_generator_model(request),
        approved=True, note=body.note,
    )
    _queue(request).update(job_id, status="approved")
    return {"job_id": job_id, "status": "approved",
            "partition_id": partition_id,
            "corpus_record_id": record_id,       # None = дубль по graph_hash
            "corpus_deduplicated": record_id is None}


@router.post("/jobs/{job_id}/reject")
def reject_job(job_id: str, body: RejectRequest, request: Request,
               ident: Identity = Depends(require_identity)) -> dict:
    """S6: отклонить с причиной — причина уходит в лог эскалаций."""
    job = _visible_job(request, job_id, ident)
    if job["status"] != AWAITING_HUMAN:
        raise HTTPException(
            status_code=409,
            detail=f"Джоба в статусе {job['status']!r} — отклонять можно "
                   f"только awaiting_human.")
    cfg = request.app.state.contour_config
    _corpus(request).write_escalation(
        job_id, job["description"], f"отклонено человеком: {body.reason}",
        job.get("rounds") or [],
        catalog_version=_catalog_version(), engine_commit=cfg.engine_commit)
    _queue(request).update(job_id, status=REJECTED, error=body.reason)
    return {"job_id": job_id, "status": REJECTED}


def _catalog_version() -> str:
    from core import graph_api
    return graph_api.catalog_version()


def _generator_model(request: Request) -> str:
    try:
        return request.app.state.contour_providers.get(TASK_GENERATE).name
    except Exception:
        return ""
