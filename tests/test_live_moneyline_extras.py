"""Unit-тесты для live moneyline extras (R39.2, паритет с enrichment)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sports_forecast.betting.edge_decision import (
    BetDecision,
    EdgeDecisionParams,
    compute_edge,
    decide_bet,
)
from sports_forecast.betting.live_moneyline_extras import (
    build_live_moneyline_extras,
    match_dt_utc,
    nhl_live_match_ref_from_prediction,
    proba_home_from_prediction,
)
from sports_forecast.data.providers.odds.live_nhl_pinnacle import PinnacleH2HQuote


_API_KEYS = (
    "pinnacle_home_decimal",
    "pinnacle_away_decimal",
    "edge_home",
    "edge_away",
    "bet_decision_home",
    "bet_decision_away",
    "live_odds_status",
)


def _quote(
    *,
    dh: float | None = 2.0,
    da: float | None = 1.9,
) -> PinnacleH2HQuote:
    return PinnacleH2HQuote(
        odds_api_event_id="evt",
        home_team="Home",
        away_team="Away",
        commence_utc=None,
        decimal_home=dh,
        decimal_away=da,
    )


@pytest.mark.parametrize(
    ("status",),
    [
        ("missing_api_key",),
        ("fetch_failed",),
        ("no_quote",),
    ],
)
def test_build_extras_quote_none_preserves_status(status: str) -> None:
    params = EdgeDecisionParams(edge_threshold=0.03, min_odds=1.01)
    got = build_live_moneyline_extras(
        proba_home=0.5,
        quote=None,
        params=params,
        status=status,
    )
    assert set(got.keys()) == set(_API_KEYS)
    assert got["pinnacle_home_decimal"] is None
    assert got["pinnacle_away_decimal"] is None
    assert got["edge_home"] is None
    assert got["edge_away"] is None
    assert got["bet_decision_home"] is None
    assert got["bet_decision_away"] is None
    assert got["live_odds_status"] == status


def test_build_extras_ok_quote_matches_edge_decision() -> None:
    params = EdgeDecisionParams(edge_threshold=0.03, min_odds=1.01)
    proba = 0.55
    q = _quote(dh=2.0, da=1.9)
    got = build_live_moneyline_extras(
        proba_home=proba,
        quote=q,
        params=params,
        status="ok",
    )
    assert got["pinnacle_home_decimal"] == 2.0
    assert got["pinnacle_away_decimal"] == 1.9
    assert got["edge_home"] == pytest.approx(float(compute_edge(proba, 2.0)))
    assert got["edge_away"] == pytest.approx(float(compute_edge(1.0 - proba, 1.9)))
    dec_h, _ = decide_bet(proba, 2.0, params)
    assert got["bet_decision_home"] == dec_h.value
    d_away, _ = decide_bet(1.0 - proba, 1.9, params)
    assert got["bet_decision_away"] == d_away.value
    assert got["live_odds_status"] == "ok"


def test_build_extras_proba_none_partial_quote_when_line_ok() -> None:
    params = EdgeDecisionParams(edge_threshold=0.03, min_odds=1.01)
    got = build_live_moneyline_extras(
        proba_home=None,
        quote=_quote(),
        params=params,
        status="ok",
    )
    assert got["bet_decision_home"] == BetDecision.INSUFFICIENT_DATA.value
    assert got["bet_decision_away"] == BetDecision.INSUFFICIENT_DATA.value
    assert got["live_odds_status"] == "partial_quote"
    assert got["edge_home"] is None
    assert got["edge_away"] is None


@pytest.mark.parametrize(
    ("proba", "threshold", "want_decision"),
    [
        (0.55, 0.06, BetDecision.NO_BET),
        (0.55, 0.05, BetDecision.BET),
    ],
)
def test_build_extras_bet_vs_no_bet_threshold(
    proba: float,
    threshold: float,
    want_decision: BetDecision,
) -> None:
    params = EdgeDecisionParams(edge_threshold=threshold, min_odds=1.01)
    got = build_live_moneyline_extras(
        proba_home=proba,
        quote=_quote(dh=2.0, da=2.0),
        params=params,
        status="ok",
    )
    d, _ = decide_bet(proba, 2.0, params)
    assert d is want_decision
    assert got["bet_decision_home"] == want_decision.value
    d_away, _ = decide_bet(1.0 - proba, 2.0, params)
    assert got["bet_decision_away"] == d_away.value


def test_build_extras_partial_line_home_missing() -> None:
    params = EdgeDecisionParams(edge_threshold=0.01, min_odds=1.01)
    got = build_live_moneyline_extras(
        proba_home=0.5,
        quote=_quote(dh=None, da=2.0),
        params=params,
        status="ok",
    )
    assert got["live_odds_status"] == "partial_quote"
    assert got["edge_home"] is None
    assert got["edge_away"] == pytest.approx(float(compute_edge(0.5, 2.0)))
    assert got["bet_decision_home"] == BetDecision.INSUFFICIENT_DATA.value
    assert got["bet_decision_away"] == decide_bet(0.5, 2.0, params)[0].value
    naive = datetime(2024, 1, 15, 18, 30, 0)
    u = match_dt_utc(naive)
    assert u is not None
    assert u.tzinfo == timezone.utc
    assert u.hour == 18

    aware = datetime(2024, 1, 15, 18, 30, 0, tzinfo=timezone.utc)
    assert match_dt_utc(aware) == aware
    assert match_dt_utc(None) is None


def test_proba_home_column_then_json() -> None:
    pred = SimpleNamespace(
        match_id="1",
        home_player="H",
        away_player="A",
        match_datetime=None,
        proba_home=0.61,
        predictions_json='{"home_win": 0.99}',
    )
    assert proba_home_from_prediction(pred) == pytest.approx(0.61)

    pred2 = SimpleNamespace(
        match_id="1",
        home_player="H",
        away_player="A",
        match_datetime=None,
        proba_home=None,
        predictions_json='{"home_win": 0.52}',
    )
    assert proba_home_from_prediction(pred2) == pytest.approx(0.52)


def test_nhl_live_match_ref_from_prediction() -> None:
    dt = datetime(2024, 3, 1, 12, 0, 0)
    pred = SimpleNamespace(
        match_id=999,
        home_player="X",
        away_player="Y",
        match_datetime=dt,
        proba_home=None,
        predictions_json="{}",
    )
    ref = nhl_live_match_ref_from_prediction(pred)
    assert ref.match_id == "999"
    assert ref.home_team == "X"
    assert ref.away_team == "Y"
    assert ref.commence_utc is not None
    assert ref.commence_utc.tzinfo == timezone.utc


def test_end_to_end_same_as_direct_build() -> None:
    """Паритет: proba из предикта + те же аргументы, что у enrichment-ветки success."""
    params = EdgeDecisionParams(edge_threshold=0.03, min_odds=1.01)
    pred = SimpleNamespace(
        match_id="m1",
        home_player="H",
        away_player="A",
        match_datetime=None,
        proba_home=0.55,
        predictions_json="{}",
    )
    q = _quote()
    direct = build_live_moneyline_extras(
        proba_home=proba_home_from_prediction(pred),
        quote=q,
        params=params,
        status="ok",
    )
    assert direct["pinnacle_home_decimal"] == q.decimal_home
    assert direct["bet_decision_home"] == BetDecision.BET.value
    assert direct["bet_decision_away"] == decide_bet(0.45, q.decimal_away, params)[0].value
