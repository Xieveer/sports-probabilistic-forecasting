"""
FastAPI application — тонкий read-only API.

Не выполняет тяжёлых вычислений.
Предсказания предвычисляются batch pipeline и хранятся в БД.

Prometheus метрики доступны на ``/metrics``.

Запуск::

    uvicorn sports_forecast.service.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from sports_forecast.service.db.engine import get_engine, init_db
from sports_forecast.service.routers import health, predictions
from sports_forecast.version import get_service_version


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init DB on startup."""
    get_engine()
    init_db()
    yield


app = FastAPI(
    title="Sports Probabilistic Forecasting API",
    description=(
        "Публичный read-only слой (`/predict`, `/health`) — выдача предвычисленных "
        "предсказаний из БД; к нему относится целевой SLA. "
        "Префикс `/internal/predict` — операционные endpoint-ы (кеш, stale); "
        "отдельный контракт, без публичного SLA."
    ),
    version=get_service_version(),
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "health",
            "description": "Проверка доступности сервиса и БД.",
        },
        {
            "name": "predictions",
            "description": (
                "Публичные read-only методы витрины предсказаний (целевой SLA по latency и доступности)."
            ),
        },
        {
            "name": "operations",
            "description": (
                "Внутренние операции: LRU-кеш, сброс кеша, список stale для планировщика. "
                "Не смешивать с показателями публичного API."
            ),
        },
    ],
)

# Register routers
app.include_router(health.router)
app.include_router(predictions.public_router)
app.include_router(predictions.operations_router)

# Prometheus /metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Redirect to docs."""
    return {"message": "Sports Forecast API", "docs": "/docs"}
