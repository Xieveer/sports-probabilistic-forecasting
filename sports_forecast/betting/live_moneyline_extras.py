"""
Чистая логика полей live Pinnacle moneyline для ответа API и оркестрации (R39).

Собирает словарь ``pinnacle_*``, ``edge_home``, ``bet_decision_home``, ``live_odds_status``
из вероятности дома, котировки :class:`~sports_forecast.data.providers.odds.live_nhl_pinnacle.PinnacleH2HQuote`
и порогов :class:`~sports_forecast.betting.edge_decision.EdgeDecisionParams``. HTTP, БД и батч-fetch
остаются в :mod:`sports_forecast.service.live_odds_enrichment`; оркестрация может импортировать
только этот модуль из ``betting`` без зависимости от FastAPI.

Структурный тип :class:`LiveMoneylinePredictionInput` совместим с
:class:`~sports_forecast.service.db.models.Prediction`; пакет ``betting`` намеренно не импортирует ``service``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from sports_forecast.betting.edge_decision import (
    BetDecision,
    EdgeDecisionParams,
    compute_edge,
    decide_bet,
)
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
    NHLLiveMatchRef,
    PinnacleH2HQuote,
)


class LiveMoneylinePredictionInput(Protocol):
    """Минимальный контракт строки предсказания для NHL moneyline live extras."""

    match_id: str | int
    home_player: str | None
    away_player: str | None
    match_datetime: datetime | None
    proba_home: float | None
    predictions_json: str


def match_dt_utc(dt: datetime | None) -> datetime | None:
    """Нормализовать момент начала матча к UTC (aware).

    Args:
        dt: Наивное время интерпретируется как UTC.

    Returns:
        Aware ``datetime`` в UTC или ``None``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def proba_home_from_prediction(pred: LiveMoneylinePredictionInput) -> float | None:
    """Извлечь вероятность победы дома из колонки ``proba_home`` или JSON ``home_win``.

    Args:
        pred: Строка витрины с ``predictions_json`` и опционально ``proba_home``.

    Returns:
        Вероятность в ``[0, 1]`` при успехе, иначе ``None``.
    """
    if pred.proba_home is not None:
        try:
            return float(pred.proba_home)
        except (TypeError, ValueError):
            pass
    try:
        d = json.loads(pred.predictions_json)
        v = d.get("home_win")
        if v is None:
            return None
        return float(v)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def nhl_live_match_ref_from_prediction(pred: LiveMoneylinePredictionInput) -> NHLLiveMatchRef:
    """Собрать ссылку на матч для батч-запроса The Odds API (NHL Pinnacle h2h).

    Args:
        pred: Строка с ``match_id``, именами сторон и временем матча.

    Returns:
        :class:`~sports_forecast.data.providers.odds.live_nhl_pinnacle.NHLLiveMatchRef`.
    """
    return NHLLiveMatchRef(
        match_id=str(pred.match_id),
        home_team=str(pred.home_player or ""),
        away_team=str(pred.away_player or ""),
        commence_utc=match_dt_utc(pred.match_datetime),
    )


def build_live_moneyline_extras(
    *,
    proba_home: float | None,
    quote: PinnacleH2HQuote | None,
    params: EdgeDecisionParams,
    status: str,
) -> dict[str, Any]:
    """Построить словарь опциональных полей ответа API для live moneyline (дом).

    Логика совпадает с прежним вычислением в ``live_odds_enrichment`` (ветки для отсутствующей
    котировки, частичной линии, ``compute_edge`` / ``decide_bet``, финальный ``live_odds_status``).

    Args:
        proba_home: Модельная вероятность дома или ``None``.
        quote: Котировка Pinnacle h2h или ``None``.
        params: Пороги edge / минимальный коэффициент.
        status: Внешний статус (``ok``, ``no_quote``, ``missing_api_key``, …).

    Returns:
        Ключи: ``pinnacle_home_decimal``, ``pinnacle_away_decimal``, ``edge_home``,
        ``bet_decision_home``, ``live_odds_status``.
    """
    if quote is None:
        return {
            "pinnacle_home_decimal": None,
            "pinnacle_away_decimal": None,
            "edge_home": None,
            "bet_decision_home": None,
            "live_odds_status": status,
        }

    ph, pa = quote.decimal_home, quote.decimal_away
    line_ok = ph is not None and pa is not None
    line_st = "ok" if line_ok else "partial_quote"

    p_h = proba_home
    edge_home: float | None = None
    if p_h is not None and ph is not None:
        try:
            edge_home = float(compute_edge(p_h, float(ph)))
        except ValueError:
            edge_home = None
            line_st = "partial_quote"

    if p_h is None:
        decision = BetDecision.INSUFFICIENT_DATA
    else:
        decision, _ = decide_bet(p_h, ph, params)

    if decision is BetDecision.INSUFFICIENT_DATA and line_st == "ok":
        line_st = "partial_quote"

    final_status = status if status != "ok" else line_st

    return {
        "pinnacle_home_decimal": ph,
        "pinnacle_away_decimal": pa,
        "edge_home": edge_home,
        "bet_decision_home": decision.value,
        "live_odds_status": final_status,
    }


__all__ = [
    "LiveMoneylinePredictionInput",
    "build_live_moneyline_extras",
    "match_dt_utc",
    "nhl_live_match_ref_from_prediction",
    "proba_home_from_prediction",
]
