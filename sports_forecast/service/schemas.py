"""
Pydantic-схемы для FastAPI endpoints.

Определяет контракт request/response для prediction API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────
# RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────


class ModelInfo(BaseModel):
    """Информация о модели, сделавшей предсказание."""

    version: str = Field(..., description="Версия модели")
    algorithm: str = Field(..., description="Алгоритм (catboost, lgbm, ...)")
    featureset: str = Field(..., description="Набор фичей (basic, advanced)")


class PredictionResponse(BaseModel):
    """Ответ API с предсказанием для одного матча + рынка."""

    match_id: str = Field(..., description="Идентификатор матча")
    tournament: str = Field(..., description="Турнир")
    market: str = Field(..., description="Тип рынка (winner, total)")
    market_spec: str = Field(..., description="Спецификация (winner, total_over)")

    # Players
    home_player: str | None = Field(None, description="Домашний игрок")
    away_player: str | None = Field(None, description="Гостевой игрок")
    match_datetime: datetime | None = Field(None, description="Время матча")

    # Predictions
    predictions: dict[str, float] = Field(..., description="Вероятности {outcome: probability}")

    # Model info
    model: ModelInfo

    # Timestamps
    prediction_ts: datetime = Field(..., description="Время расчёта")
    status: str = Field(..., description="Статус: ok, stale, not_ready, error")

    class Config:
        from_attributes = True


class PredictionListResponse(BaseModel):
    """Список предсказаний (для турнира или множества матчей)."""

    count: int
    predictions: list[PredictionResponse]


class HealthResponse(BaseModel):
    """Ответ healthcheck."""

    status: str = "ok"
    version: str = "2.0.0"
    db_connected: bool = True
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Ответ при ошибке."""

    error: str
    detail: str | None = None
