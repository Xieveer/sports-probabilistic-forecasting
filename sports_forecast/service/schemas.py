"""
Pydantic-схемы для FastAPI endpoints.

Определяет контракт request/response для prediction API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from sports_forecast.version import get_service_version


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

    # Live Pinnacle (The Odds API) + value edge — только NHL moneyline при live_pinnacle=true (R37.5)
    pinnacle_home_decimal: float | None = Field(
        None,
        description="Текущий decimal Pinnacle на домашнюю сторону (h2h), если доступен",
    )
    pinnacle_away_decimal: float | None = Field(
        None,
        description="Текущий decimal Pinnacle на гостевую сторону (h2h), если доступен",
    )
    edge_home: float | None = Field(
        None,
        description="Edge домашней стороны: P(home) − 1 / pinnacle_home_decimal",
    )
    edge_away: float | None = Field(
        None,
        description="Edge гостевой стороны: P(away) − 1 / pinnacle_away_decimal",
    )
    bet_decision_home: str | None = Field(
        None,
        description="Решение по порогу (дом): bet | no_bet | insufficient_data (conf/service_api.yaml)",
    )
    bet_decision_away: str | None = Field(
        None,
        description="Решение по порогу (гость): bet | no_bet | insufficient_data",
    )
    live_odds_status: str | None = Field(
        None,
        description=(
            "Состояние live-обогащения: ok, partial_quote, no_quote, missing_api_key, fetch_failed, "
            "disabled, skipped_not_nhl, skipped_unsupported_market"
        ),
    )

    class Config:
        from_attributes = True


class PredictionListResponse(BaseModel):
    """Список предсказаний (для турнира или множества матчей)."""

    count: int
    predictions: list[PredictionResponse]


class HealthResponse(BaseModel):
    """Ответ healthcheck."""

    status: str = "ok"
    version: str = Field(default_factory=get_service_version)
    db_connected: bool = True
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Ответ при ошибке."""

    error: str
    detail: str | None = None


class StaleInfo(BaseModel):
    """Информация об устаревшем предсказании (для batch scheduling)."""

    match_id: str = Field(..., description="ID матча")
    tournament: str = Field(..., description="Турнир")
    market: str = Field(..., description="Тип рынка")
    market_spec: str = Field(..., description="Спецификация")
    prediction_ts: datetime | None = Field(None, description="Время последнего расчёта")
    age_hours: float = Field(0, description="Возраст предсказания в часах")
