"""
Health check endpoints.

Проверяет доступность сервиса и подключение к БД.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
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
    """Проверить liveness процесса без проверки внешних зависимостей.

    Returns:
        Статус процесса. Поле ``db_connected`` не определяет HTTP-статус.
    """
    return HealthResponse(
        status="ok",
        db_connected=False,
        timestamp=datetime.now(tz=UTC),
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness check",
)
def readiness_check() -> HealthResponse | JSONResponse:
    """Проверить готовность API обслуживать данные из обязательной БД.

    Raises:
        JSONResponse: С HTTP 503, если PostgreSQL недоступна.
    """
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        response = HealthResponse(
            status="not_ready",
            db_connected=False,
            timestamp=datetime.now(tz=UTC),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(response),
        )

    return HealthResponse(
        status="ok",
        db_connected=True,
        timestamp=datetime.now(tz=UTC),
    )
