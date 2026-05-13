"""
Live Pinnacle (The Odds API) для ответов публичного prediction API (R37.5).

Один батч-запрос на список предсказаний NHL moneyline (``winner`` / ``winner_withOT``);
тяжёлые фичи не считаются — только лёгкий HTTP + сопоставление из
:mod:`sports_forecast.data.providers.odds.live_nhl_pinnacle`.

При ``live_pinnacle=false`` или отсутствии ``ODDS_API_KEY`` поля остаются пустыми,
``live_odds_status`` фиксирует причину (см. OpenAPI у ``/predict/*``).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

from sports_forecast.betting.edge_decision import (
    BetDecision,
    EdgeDecisionParams,
    compute_edge,
    decide_bet,
)
from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.client import QuotaBudgetError
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
    NHLLiveMatchRef,
    PinnacleH2HQuote,
    build_odds_client_for_live,
    fetch_nhl_pinnacle_quotes_for_refs,
)
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.service_api_settings import load_edge_decision_params
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _is_nhl_tournament(tournament: str) -> bool:
    t = str(tournament).strip().lower()
    return t == "nhl" or t == "nhl_train" or t.startswith("nhl_")


def _is_moneyline_market(market: str) -> bool:
    return str(market).strip() in ("winner", "winner_withOT")


def _is_nhl_moneyline(pred: Prediction) -> bool:
    return _is_nhl_tournament(pred.tournament) and _is_moneyline_market(pred.market)


def _match_dt_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pred_to_ref(pred: Prediction) -> NHLLiveMatchRef:
    return NHLLiveMatchRef(
        match_id=str(pred.match_id),
        home_team=str(pred.home_player or ""),
        away_team=str(pred.away_player or ""),
        commence_utc=_match_dt_utc(pred.match_datetime),
    )


def _proba_home(pred: Prediction) -> float | None:
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


def _compute_extras_for_pred(
    pred: Prediction,
    quote: PinnacleH2HQuote | None,
    *,
    params: EdgeDecisionParams,
    status: str,
) -> dict[str, Any]:
    """Собрать поля live odds + edge для домашней стороны (moneyline)."""
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

    p_h = _proba_home(pred)
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


def _registry() -> TeamNameRegistry:
    return load_nhl_team_name_registry()


def _fetch_quotes_map(preds: list[Prediction]) -> dict[str, PinnacleH2HQuote | None]:
    by_mid: dict[str, Prediction] = {}
    for p in preds:
        mid = str(p.match_id)
        if mid not in by_mid:
            by_mid[mid] = p
    refs = [_pred_to_ref(by_mid[mid]) for mid in sorted(by_mid)]
    book_cfg = load_bookmaker_config("the_odds_api")
    if book_cfg is None:
        raise RuntimeError("the_odds_api bookmaker config missing")
    client = build_odds_client_for_live(book_cfg)
    return fetch_nhl_pinnacle_quotes_for_refs(
        refs,
        book_cfg=book_cfg,
        team_registry=_registry(),
        client=client,
    )


def batch_live_response_extras(
    preds: list[Prediction],
    *,
    live_pinnacle: bool = True,
) -> dict[int, dict[str, Any]]:
    """Построить kwargs для опциональных полей :class:`~sports_forecast.service.schemas.PredictionResponse`.

    Args:
        preds: Строки витрины (ожидается загруженный PK ``id``).
        live_pinnacle: ``False`` — не вызывать The Odds API (статус ``disabled``).

    Returns:
        ``pred.id`` → словарь полей ``pinnacle_*``, ``edge_home``, ``bet_decision_home``,
        ``live_odds_status``.
    """
    out: dict[int, dict[str, Any]] = {}
    if not preds:
        return out

    disabled: dict[str, Any] = {
        "pinnacle_home_decimal": None,
        "pinnacle_away_decimal": None,
        "edge_home": None,
        "bet_decision_home": None,
        "live_odds_status": "disabled",
    }
    if not live_pinnacle:
        for p in preds:
            out[int(p.id)] = dict(disabled)
        return out

    neutral: dict[str, Any] = {
        "pinnacle_home_decimal": None,
        "pinnacle_away_decimal": None,
        "edge_home": None,
        "bet_decision_home": None,
        "live_odds_status": None,
    }

    nhl_ml = [p for p in preds if _is_nhl_moneyline(p)]
    quotes_by_match: dict[str, PinnacleH2HQuote | None] | None = None
    fetch_error: str | None = None

    if nhl_ml:
        if not os.environ.get("ODDS_API_KEY", "").strip():
            fetch_error = "missing_api_key"
        else:
            try:
                quotes_by_match = _fetch_quotes_map(nhl_ml)
            except (
                QuotaBudgetError,
                requests.RequestException,
                OSError,
                ValueError,
                RuntimeError,
            ) as e:
                logger.warning("Live Pinnacle: fetch failed (%s)", type(e).__name__)
                fetch_error = "fetch_failed"

    params = load_edge_decision_params()

    for p in preds:
        pid = int(p.id)
        if not _is_nhl_tournament(p.tournament):
            row = dict(neutral)
            row["live_odds_status"] = "skipped_not_nhl"
            out[pid] = row
            continue
        if not _is_moneyline_market(p.market):
            row = dict(neutral)
            row["live_odds_status"] = "skipped_unsupported_market"
            out[pid] = row
            continue

        if fetch_error == "missing_api_key":
            out[pid] = _compute_extras_for_pred(p, None, params=params, status="missing_api_key")
            continue
        if fetch_error == "fetch_failed":
            out[pid] = _compute_extras_for_pred(p, None, params=params, status="fetch_failed")
            continue

        assert quotes_by_match is not None  # при наличии NHL ML и успешном fetch
        q = quotes_by_match.get(str(p.match_id))
        st = "ok" if q is not None else "no_quote"
        out[pid] = _compute_extras_for_pred(p, q, params=params, status=st)

    return out


__all__ = ["batch_live_response_extras"]
