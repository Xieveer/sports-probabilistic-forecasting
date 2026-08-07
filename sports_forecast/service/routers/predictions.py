"""
Prediction API endpoints.

**Публичный контракт** (``public_router``, префикс ``/predict``): только чтение
из витрины предсказаний; к этим путям относится целевой SLA latency/доступности.

**Операционный контракт** (``operations_router``, префикс ``/internal/predict``):
кеш, сброс кеша, stale-лист для планировщика batch — не часть публичного SLA;
предназначены для внутренних клиентов (оркестрация, администрирование).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import PredictionRepository
from sports_forecast.service.live_odds_enrichment import batch_live_response_extras
from sports_forecast.service.schemas import (
    ModelInfo,
    PredictionListResponse,
    PredictionResponse,
    StaleInfo,
)


public_router = APIRouter(prefix="/predict", tags=["predictions"])
operations_router = APIRouter(
    prefix="/internal/predict",
    tags=["operations"],
)


def _to_response(
    pred: Prediction, *, live_extras: dict[str, Any] | None = None
) -> PredictionResponse:
    """Конвертировать ORM-объект в Pydantic-ответ.

    Args:
        pred: Строка витрины.
        live_extras: Опциональные поля live Pinnacle / edge (см. :func:`batch_live_response_extras`).
    """
    predictions = json.loads(pred.predictions_json)
    base: dict[str, Any] = {
        "match_id": pred.match_id,
        "tournament": pred.tournament,
        "market": pred.market,
        "market_spec": pred.market_spec,
        "home_player": pred.home_player,
        "away_player": pred.away_player,
        "match_datetime": pred.match_datetime,
        "predictions": predictions,
        "model": ModelInfo(
            version=pred.model_version,
            algorithm=pred.algorithm,
            featureset=pred.featureset,
        ),
        "prediction_ts": pred.prediction_ts,
        "status": pred.status,
    }
    if live_extras is not None:
        base.update(live_extras)
    else:
        base.update(
            {
                "pinnacle_home_decimal": None,
                "pinnacle_away_decimal": None,
                "edge_home": None,
                "edge_away": None,
                "bet_decision_home": None,
                "bet_decision_away": None,
                "live_odds_status": None,
            }
        )
    return PredictionResponse(**base)


@public_router.get(
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
    live_pinnacle: bool = Query(
        True,
        description=(
            "Для NHL moneyline: один запрос The Odds API и поля pinnacle_*, edge_home/edge_away, "
            "bet_decision_home/bet_decision_away. ``false`` — без внешнего HTTP (поля пустые, статус ``disabled``)."
        ),
    ),
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

    extras = batch_live_response_extras([pred], live_pinnacle=live_pinnacle).get(int(pred.id))
    return _to_response(pred, live_extras=extras)


@public_router.get(
    "/match/{match_id}/all",
    response_model=PredictionListResponse,
    summary="Все предсказания для матча (все рынки)",
)
def get_all_predictions_for_match(
    match_id: str,
    live_pinnacle: bool = Query(
        True,
        description="См. ``/predict/{match_id}`` — батч live Pinnacle для NHL moneyline в списке.",
    ),
) -> PredictionListResponse:
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

    extras_map = batch_live_response_extras(preds, live_pinnacle=live_pinnacle)
    return PredictionListResponse(
        count=len(preds),
        predictions=[_to_response(p, live_extras=extras_map.get(int(p.id))) for p in preds],
    )


@public_router.get(
    "/upcoming/{tournament}",
    response_model=PredictionListResponse,
    summary="Предсказания для предстоящих матчей турнира",
)
def get_upcoming(
    tournament: str,
    market: str = Query(
        "winner",
        description=(
            "Тип рынка. Для NHL полного матча (вкл. ОТ/буллиты) используйте ``winner_withOT``; "
            "базовый регламентный исход — ``winner`` (см. ``conf/market`` / ``HOW_TO_ADD_NEW_MARKET``)."
        ),
    ),
    market_spec: str | None = Query(
        None,
        description=(
            "Спецификация рынка (точное совпадение с витриной). Примеры NHL: ``winner`` или "
            "``winner_withOT`` в паре с ``market=winner`` / ``market=winner_withOT`` согласно "
            "обученному артефакту (часто ``market_spec`` совпадает с ``market``)."
        ),
    ),
    hours: int = Query(
        48,
        ge=1,
        le=8760,
        description=(
            "Окно в часах от текущего момента UTC вперёд: попадают только матчи с известным "
            "``match_datetime`` в интервале [сейчас, сейчас + hours]. Увеличьте значение, если "
            "нужен горизонт дольше 48 ч."
        ),
    ),
    live_pinnacle: bool = Query(
        True,
        description=(
            "Для турнира NHL и moneyline: один батч-запрос The Odds API на весь список; "
            "поля ``pinnacle_*``, ``edge_*``, ``bet_decision_*`` на строку. ``false`` — без HTTP."
        ),
    ),
) -> PredictionListResponse:
    """Получить актуальные предсказания для предстоящих матчей.

    В выборку входят только записи со статусом ``ok``, непустым временем матча и
    ``match_datetime`` в пределах указанного окна от текущего UTC.

    Args:
        tournament: Название турнира (например ``nhl``, ``uel_kz_1``).
        market: Тип рынка.
        market_spec: Опциональный фильтр по спецификации (NHL OT — см. описание параметра).
        hours: Горизонт в часах (по умолчанию 48).

    Returns:
        Список предсказаний.
    """
    with get_session() as session:
        repo = PredictionRepository(session)
        preds = repo.get_upcoming_predictions(
            tournament=tournament,
            market=market,
            market_spec=market_spec,
            hours=hours,
        )

    extras_map = batch_live_response_extras(preds, live_pinnacle=live_pinnacle)
    return PredictionListResponse(
        count=len(preds),
        predictions=[_to_response(p, live_extras=extras_map.get(int(p.id))) for p in preds],
    )


# CACHE: In-memory LRU для горячих предсказаний

# Время жизни кеша (секунды). После этого кеш инвалидируется.
_CACHE_TTL_SECONDS = 300  # 5 минут
_cache_timestamp: float = 0.0


def _is_cache_valid() -> bool:
    """Проверить, не истёк ли TTL кеша."""
    return (time.time() - _cache_timestamp) < _CACHE_TTL_SECONDS


@lru_cache(maxsize=512)
def _cached_prediction(match_id: str, market: str, market_spec: str | None) -> dict | None:
    """Кешированный запрос предсказания из БД.

    Args:
        match_id: ID матча.
        market: Тип рынка.
        market_spec: Спецификация рынка.

    Returns:
        Словарь с предсказанием или None.
    """
    with get_session() as session:
        repo = PredictionRepository(session)
        pred = repo.get_latest_prediction(
            match_id=match_id,
            market=market,
            market_spec=market_spec,
        )
    if pred is None:
        return None

    predictions = json.loads(pred.predictions_json)
    return {
        "match_id": pred.match_id,
        "tournament": pred.tournament,
        "market": pred.market,
        "market_spec": pred.market_spec,
        "home_player": pred.home_player,
        "away_player": pred.away_player,
        "match_datetime": pred.match_datetime.isoformat() if pred.match_datetime else None,
        "predictions": predictions,
        "model_version": pred.model_version,
        "algorithm": pred.algorithm,
        "featureset": pred.featureset,
        "prediction_ts": pred.prediction_ts.isoformat() if pred.prediction_ts else None,
        "status": pred.status,
    }


@operations_router.get(
    "/cached/{match_id}",
    response_model=PredictionResponse,
    summary="[Операции] Предсказание с LRU кешированием",
    responses={404: {"description": "Предсказание не найдено"}},
)
def get_prediction_cached(
    match_id: str,
    market: str = Query("winner", description="Тип рынка"),
    market_spec: str | None = Query(None, description="Спецификация рынка"),
) -> PredictionResponse:
    """Получить предсказание с in-memory LRU кешем.

    Кеш инвалидируется каждые 5 минут.
    Для сброса кеша используйте ``POST /internal/predict/cache/clear``.

    Операционный endpoint: не входит в публичный SLA.

    Args:
        match_id: ID матча.
        market: Тип рынка.
        market_spec: Спецификация рынка.

    Returns:
        Предсказание с вероятностями.

    Raises:
        HTTPException: 404 если предсказание не найдено.
    """
    global _cache_timestamp  # noqa: PLW0603

    if not _is_cache_valid():
        _cached_prediction.cache_clear()
        _cache_timestamp = time.time()

    result = _cached_prediction(match_id, market, market_spec)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Предсказание для match_id={match_id}, market={market} не найдено",
        )

    return PredictionResponse(
        match_id=result["match_id"],
        tournament=result["tournament"],
        market=result["market"],
        market_spec=result["market_spec"],
        home_player=result["home_player"],
        away_player=result["away_player"],
        match_datetime=(
            datetime.fromisoformat(result["match_datetime"]) if result["match_datetime"] else None
        ),
        predictions=result["predictions"],
        model=ModelInfo(
            version=result["model_version"],
            algorithm=result["algorithm"],
            featureset=result["featureset"],
        ),
        prediction_ts=(
            datetime.fromisoformat(result["prediction_ts"])
            if result["prediction_ts"]
            else datetime.now(tz=UTC)
        ),
        status=result["status"],
        pinnacle_home_decimal=None,
        pinnacle_away_decimal=None,
        edge_home=None,
        edge_away=None,
        bet_decision_home=None,
        bet_decision_away=None,
        live_odds_status=None,
    )


@operations_router.post(
    "/cache/clear",
    summary="[Операции] Очистить кеш предсказаний",
)
def clear_cache() -> dict[str, str]:
    """Очистить in-memory LRU кеш предсказаний.

    Используйте после batch materialization для обновления кеша.
    Операционный endpoint: не входит в публичный SLA.

    Returns:
        Сообщение об успехе.
    """
    global _cache_timestamp  # noqa: PLW0603
    _cached_prediction.cache_clear()
    _cache_timestamp = 0.0
    return {"status": "ok", "message": "Кеш очищен"}


@operations_router.get(
    "/cache/stats",
    summary="[Операции] Статистика кеша",
)
def cache_stats() -> dict[str, object]:
    """Получить статистику LRU кеша.

    Операционный endpoint: не входит в публичный SLA.

    Returns:
        Информация о кеше (hits, misses, size).
    """
    info = _cached_prediction.cache_info()
    return {
        "hits": info.hits,
        "misses": info.misses,
        "size": info.currsize,
        "maxsize": info.maxsize,
        "ttl_seconds": _CACHE_TTL_SECONDS,
        "cache_valid": _is_cache_valid(),
    }


# STALE PREDICTIONS: для batch scheduling


@operations_router.get(
    "/stale",
    response_model=list[StaleInfo],
    summary="[Операции] Список устаревших предсказаний",
)
def get_stale_predictions(
    max_age_hours: int = Query(6, description="Максимальный возраст в часах"),
    tournament: str | None = Query(None, description="Фильтр по турниру"),
) -> list[StaleInfo]:
    """Получить список предсказаний, которые устарели и требуют пересчёта.

    Используется batch scheduler для определения, какие предсказания
    нужно обновить. Операционный endpoint: не входит в публичный SLA.

    Args:
        max_age_hours: Предсказания старше этого порога считаются stale.
        tournament: Опциональный фильтр по турниру.

    Returns:
        Список устаревших предсказаний.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(hours=max_age_hours)

    with get_session() as session:
        repo = PredictionRepository(session)
        preds = repo.get_stale_predictions(cutoff=cutoff, tournament=tournament)

    return [
        StaleInfo(
            match_id=p.match_id,
            tournament=p.tournament,
            market=p.market,
            market_spec=p.market_spec,
            prediction_ts=p.prediction_ts,
            age_hours=round(
                (datetime.now(tz=UTC) - p.prediction_ts.replace(tzinfo=UTC)).total_seconds() / 3600,
                1,
            )
            if p.prediction_ts
            else 0,
        )
        for p in preds
    ]
