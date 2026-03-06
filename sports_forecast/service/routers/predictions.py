"""
Prediction API endpoints.

Все endpoints — **read-only**: предсказания предвычисляются
batch pipeline и сохраняются в БД.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import PredictionRepository
from sports_forecast.service.schemas import (
    ModelInfo,
    PredictionListResponse,
    PredictionResponse,
)


router = APIRouter(prefix="/predict", tags=["predictions"])


def _to_response(pred: Prediction) -> PredictionResponse:
    """Конвертировать ORM-объект в Pydantic-ответ."""
    predictions = json.loads(pred.predictions_json)
    return PredictionResponse(
        match_id=pred.match_id,
        tournament=pred.tournament,
        market=pred.market,
        market_spec=pred.market_spec,
        home_player=pred.home_player,
        away_player=pred.away_player,
        match_datetime=pred.match_datetime,
        predictions=predictions,
        model=ModelInfo(
            version=pred.model_version,
            algorithm=pred.algorithm,
            featureset=pred.featureset,
        ),
        prediction_ts=pred.prediction_ts,
        status=pred.status,
    )


@router.get(
    "/{match_id}",
    response_model=PredictionResponse,
    summary="Получить предсказание для матча",
    responses={
        404: {"description": "Предсказание не найдено"},
    },
)
def get_prediction(
    match_id: str,
    market: str = Query("winner", description="Тип рынка"),
    market_spec: str | None = Query(None, description="Спецификация рынка"),
) -> PredictionResponse:
    """Получить последнее актуальное предсказание для матча.

    Args:
        match_id: ID матча.
        market: Тип рынка (winner, total).
        market_spec: Спецификация (winner, total_over).

    Returns:
        Предсказание с вероятностями.

    Raises:
        HTTPException: 404 если предсказание не найдено.
    """
    with get_session() as session:
        repo = PredictionRepository(session)
        pred = repo.get_latest_prediction(
            match_id=match_id,
            market=market,
            market_spec=market_spec,
        )

    if pred is None:
        raise HTTPException(
            status_code=404,
            detail=f"Предсказание для match_id={match_id}, market={market} не найдено",
        )

    return _to_response(pred)


@router.get(
    "/match/{match_id}/all",
    response_model=PredictionListResponse,
    summary="Все предсказания для матча (все рынки)",
)
def get_all_predictions_for_match(match_id: str) -> PredictionListResponse:
    """Получить все предсказания для матча (по всем рынкам).

    Args:
        match_id: ID матча.

    Returns:
        Список предсказаний.
    """
    with get_session() as session:
        repo = PredictionRepository(session)
        preds = repo.get_predictions_by_match(match_id)

    if not preds:
        raise HTTPException(
            status_code=404,
            detail=f"Предсказания для match_id={match_id} не найдены",
        )

    return PredictionListResponse(
        count=len(preds),
        predictions=[_to_response(p) for p in preds],
    )


@router.get(
    "/upcoming/{tournament}",
    response_model=PredictionListResponse,
    summary="Предсказания для предстоящих матчей турнира",
)
def get_upcoming(
    tournament: str,
    market: str = Query("winner", description="Тип рынка"),
) -> PredictionListResponse:
    """Получить актуальные предсказания для предстоящих матчей.

    Args:
        tournament: Название турнира.
        market: Тип рынка.

    Returns:
        Список предсказаний.
    """
    with get_session() as session:
        repo = PredictionRepository(session)
        preds = repo.get_upcoming_predictions(
            tournament=tournament,
            market=market,
        )

    return PredictionListResponse(
        count=len(preds),
        predictions=[_to_response(p) for p in preds],
    )
