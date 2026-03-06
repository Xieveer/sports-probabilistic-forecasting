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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init DB on startup."""
    get_engine()
    init_db()
    yield


app = FastAPI(
    title="Sports Probabilistic Forecasting API",
    description=(
        "Read-only API для выдачи предвычисленных вероятностных предсказаний спортивных событий."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(health.router)
app.include_router(predictions.router)

# Prometheus /metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Redirect to docs."""
    return {"message": "Sports Forecast API", "docs": "/docs"}
