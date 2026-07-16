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

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def get_overview(
    request: Request,
    range_days: int = 30,
    group: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
    x_user_role: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    uid = (x_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Нет заголовка X-User-Id.")
    role = (x_user_role or "teacher").strip().lower()
    return analytics_api.overview(
        request.app.state.repo, user_id=uid, role=role,
        range_days=range_days, group=group,
    )
