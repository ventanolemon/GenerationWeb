"""
GET /analytics/overview — агрегированная аналитика преподавателя/админа.

Логика в core/analytics_api.py (headless), роутер только адаптирует HTTP и
проверяет identity. В отличие от /sync здесь идентичность ОБЯЗАТЕЛЬНА — без
dev-заглушки «видно всё»: аналитика — это данные о людях, витрина без
скоупа недопустима.
"""

from __future__ import annotations
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from core import analytics_api

from ..identity import CurrentUser

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def get_overview(
    request: Request,
    who: CurrentUser,
    range_days: int = 30,
    group: Optional[str] = None,
) -> dict[str, Any]:
    return analytics_api.overview(
        request.app.state.repo, user_id=who.login, role=who.role,
        range_days=range_days, group=group,
    )
