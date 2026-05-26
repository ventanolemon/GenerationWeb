"""
Служебные эндпоинты: /health и /.

Вынесены в отдельный роутер из main.py, чтобы тестам было проще
их подключать наравне с остальными.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(request: Request) -> dict:
    """Health-check для ASP.NET-слоя и контейнерных оркестраторов."""
    registry = getattr(request.app.state, "registry", None)
    return {
        "status": "ok",
        "generators": len(registry.all_ids()) if registry is not None else 0,
    }


@router.get("/")
def root() -> dict:
    """Подсказка, куда идти за документацией."""
    return {
        "service": "Generator Microservice",
        "docs": "/docs",
        "health": "/health",
    }
