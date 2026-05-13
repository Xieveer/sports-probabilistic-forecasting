"""Тесты для edge / bet decision (R37.3)."""

from __future__ import annotations

import pytest

from sports_forecast.betting.edge_decision import (
    BetDecision,
    EdgeDecisionParams,
    compute_edge,
    decide_bet,
    implied_probability_from_decimal,
)
from sports_forecast.service.service_api_settings import (
    load_edge_decision_params,
    reset_service_api_settings_cache,
)


def test_implied_probability_from_decimal() -> None:
    assert implied_probability_from_decimal(2.0) == pytest.approx(0.5)


def test_implied_probability_invalid() -> None:
    with pytest.raises(ValueError):
        implied_probability_from_decimal(1.0)
    with pytest.raises(ValueError):
        implied_probability_from_decimal(float("nan"))


def test_decide_bet_above_threshold() -> None:
    params = EdgeDecisionParams(edge_threshold=0.03, min_odds=1.01)
    # p=0.55, odds=2.0 -> implied 0.5, edge 0.05 > 0.03
    d, edge = decide_bet(0.55, 2.0, params)
    assert d is BetDecision.BET
    assert edge == pytest.approx(0.05)


def test_decide_bet_at_threshold_inclusive() -> None:
    """На границе ``edge == threshold`` — ``BET`` (инклюзивное ``>=``)."""
    params = EdgeDecisionParams(edge_threshold=0.05, min_odds=1.01)
    d, edge = decide_bet(0.55, 2.0, params)
    assert d is BetDecision.BET
    assert edge == pytest.approx(0.05)


def test_decide_bet_below_threshold() -> None:
    params = EdgeDecisionParams(edge_threshold=0.06, min_odds=1.01)
    d, edge = decide_bet(0.55, 2.0, params)
    assert d is BetDecision.NO_BET
    assert edge == pytest.approx(0.05)


def test_decide_bet_insufficient_odds() -> None:
    params = EdgeDecisionParams(edge_threshold=0.01, min_odds=1.10)
    d, edge = decide_bet(0.9, 1.05, params)
    assert d is BetDecision.INSUFFICIENT_DATA
    assert edge is None


def test_decide_bet_insufficient_proba() -> None:
    params = EdgeDecisionParams(edge_threshold=0.01)
    d, edge = decide_bet(1.1, 2.0, params)
    assert d is BetDecision.INSUFFICIENT_DATA
    assert edge is None


def test_decide_bet_none_inputs() -> None:
    params = EdgeDecisionParams(edge_threshold=0.01)
    assert decide_bet(None, 2.0, params)[0] is BetDecision.INSUFFICIENT_DATA
    assert decide_bet(0.5, None, params)[0] is BetDecision.INSUFFICIENT_DATA


def test_compute_edge_matches_implied() -> None:
    assert compute_edge(0.6, 2.0) == pytest.approx(0.1)


def test_load_edge_params_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_service_api_settings_cache()
    monkeypatch.setenv("SERVICE_API_EDGE_THRESHOLD", "0.11")
    monkeypatch.setenv("SERVICE_API_MIN_ODDS", "1.2")
    try:
        p = load_edge_decision_params()
        assert p.edge_threshold == pytest.approx(0.11)
        assert p.min_odds == pytest.approx(1.2)
    finally:
        monkeypatch.delenv("SERVICE_API_EDGE_THRESHOLD", raising=False)
        monkeypatch.delenv("SERVICE_API_MIN_ODDS", raising=False)
        reset_service_api_settings_cache()
