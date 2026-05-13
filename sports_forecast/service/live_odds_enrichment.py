"""
Live Pinnacle (The Odds API) для ответов публичного prediction API (R37.5).

Один батч-запрос на список предсказаний NHL moneyline (``winner`` / ``winner_withOT``);
тяжёлые фичи не считаются — только лёгкий HTTP + сопоставление из
:mod:`sports_forecast.data.providers.odds.live_nhl_pinnacle`.

При ``live_pinnacle=false`` или отсутствии ``ODDS_API_KEY`` поля остаются пустыми,
``live_odds_status`` фиксирует причину (см. OpenAPI у ``/predict/*``).
"""

from __future__ import annotations

import os
from typing import Any

import requests

from sports_forecast.betting.live_moneyline_extras import (
    build_live_moneyline_extras,
    nhl_live_match_ref_from_prediction,
    proba_home_from_prediction,
)
from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.client import QuotaBudgetError
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
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


def _registry() -> TeamNameRegistry:
    return load_nhl_team_name_registry()


def _fetch_quotes_map(preds: list[Prediction]) -> dict[str, PinnacleH2HQuote | None]:
    by_mid: dict[str, Prediction] = {}
    for p in preds:
        mid = str(p.match_id)
        if mid not in by_mid:
            by_mid[mid] = p
    refs = [nhl_live_match_ref_from_prediction(by_mid[mid]) for mid in sorted(by_mid)]
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
        ``pred.id`` → словарь полей ``pinnacle_*``, ``edge_home`` / ``edge_away``,
        ``bet_decision_home`` / ``bet_decision_away``, ``live_odds_status``.
    """
    out: dict[int, dict[str, Any]] = {}
    if not preds:
        return out

    disabled: dict[str, Any] = {
        "pinnacle_home_decimal": None,
        "pinnacle_away_decimal": None,
        "edge_home": None,
        "edge_away": None,
        "bet_decision_home": None,
        "bet_decision_away": None,
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
        "edge_away": None,
        "bet_decision_home": None,
        "bet_decision_away": None,
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
            out[pid] = build_live_moneyline_extras(
                proba_home=proba_home_from_prediction(p),
                quote=None,
                params=params,
                status="missing_api_key",
            )
            continue
        if fetch_error == "fetch_failed":
            out[pid] = build_live_moneyline_extras(
                proba_home=proba_home_from_prediction(p),
                quote=None,
                params=params,
                status="fetch_failed",
            )
            continue

        assert quotes_by_match is not None  # при наличии NHL ML и успешном fetch
        q = quotes_by_match.get(str(p.match_id))
        st = "ok" if q is not None else "no_quote"
        out[pid] = build_live_moneyline_extras(
            proba_home=proba_home_from_prediction(p),
            quote=q,
            params=params,
            status=st,
        )

    return out


__all__ = ["batch_live_response_extras"]
