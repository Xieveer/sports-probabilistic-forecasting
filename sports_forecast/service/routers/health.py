"""
Health check endpoints.

Проверяет доступность сервиса и подключение к БД.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from sports_forecast.service.db.engine import get_session
from sports_forecast.service.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
)
def health_check() -> HealthResponse:
    """Проверить состояние сервиса.

    Returns:
        Статус сервиса и подключения к БД.
    """
    db_ok = True
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_connected=db_ok,
        timestamp=datetime.utcnow(),
    )
