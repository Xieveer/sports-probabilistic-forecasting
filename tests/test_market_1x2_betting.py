"""Контракт ставки по максимальному edge для одного матча 1X2."""

import numpy as np
import pandas as pd
import pytest

from sports_forecast.betting.market_1x2 import evaluate_1x2_betting


def test_wide_selects_only_max_edge_and_uses_all_events_for_coverage() -> None:
    """Два подходящих исхода дают одну ставку с наибольшим edge."""
    events = pd.DataFrame(
        {
            "id": ["a", "b"],
            "odd_home": [3.0, np.nan],
            "odd_draw": [4.0, 3.0],
            "odd_away": [4.0, 3.0],
        }
    )
    probabilities = np.array([[0.43, 0.40, 0.17], [0.4, 0.3, 0.3]])
    result = evaluate_1x2_betting(
        events,
        pd.Series([1, 0]),
        probabilities,
        is_long=False,
        classes=np.array([0, 1, 2]),
        min_edge_threshold=0.05,
        flat_stake=10,
        initial_bankroll=1000,
    )
    assert result["n_bets"] == 1
    assert result["coverage"] == 0.5
    assert result["profit_units"] == 30
    assert result["roi"] == 300
    assert result["bet_trace"].loc[0, "outcome"] == "draw"
    assert result["valid_odds_count"] == 1


def test_long_rejects_negative_draw_residual_without_dropping_event() -> None:
    """Отрицательный остаток не превращается в ставку и виден в аудите."""
    events = pd.DataFrame(
        {
            "id": ["a", "a", "b", "b"],
            "is_home": [1, 0, 1, 0],
            "odd_home": [2.5] * 4,
            "odd_draw": [3.5] * 4,
            "odd_away": [3.0] * 4,
        }
    )
    probabilities = np.array([[0.65, 0.35], [0.60, 0.40], [0.1, 0.9], [0.1, 0.9]])
    result = evaluate_1x2_betting(
        events,
        pd.Series([1, 0, 0, 1]),
        probabilities,
        is_long=True,
        classes=None,
        min_edge_threshold=0.05,
        flat_stake=10,
        initial_bankroll=1000,
    )
    assert result["rejected_distribution_count"] == 1
    assert result["n_total_events"] == 2
    assert result["n_bets"] == 1
    assert result["bet_trace"].loc[0, "id"] == "a"


def test_long_all_distributions_rejected() -> None:
    """Полностью отклонённый holdout сохраняется без недоступных метрик."""
    events = pd.DataFrame(
        {
            "id": ["a", "a", "b", "b"],
            "is_home": [1, 0, 1, 0],
            "odd_home": [2.5] * 4,
            "odd_draw": [3.5] * 4,
            "odd_away": [3.0] * 4,
        }
    )
    result = evaluate_1x2_betting(
        events,
        pd.Series([1, 0, 0, 1]),
        np.array([[0.2, 0.8]] * 4),
        is_long=True,
        classes=None,
        min_edge_threshold=-1,
        flat_stake=10,
        initial_bankroll=1000,
        sweep_thresholds=[-1, 0],
    )
    assert result["n_total_events"] == 2
    assert result["rejected_distribution_count"] == 2
    assert result["valid_distribution_count"] == 0
    assert result["market_metrics"] == {}
    assert result["n_bets"] == 0
    assert result["coverage"] == 0
    assert not result["bet_trace"]["bet_placed"].any()
    assert result["sweep_df"]["n_bets"].tolist() == [0, 0]


@pytest.mark.parametrize("is_long", [False, True])
@pytest.mark.parametrize("missing", ["odd_home", "odd_draw", "odd_away", "all"])
def test_missing_optional_odds_never_create_bets(is_long: bool, missing: str) -> None:
    """Отсутствующие коэффициенты исключают ставки, но не вероятностные метрики."""
    events = pd.DataFrame(
        {
            "id": ["a", "a"] if is_long else ["a"],
            "odd_home": [2.5] * (2 if is_long else 1),
            "odd_draw": [3.5] * (2 if is_long else 1),
            "odd_away": [3.0] * (2 if is_long else 1),
        }
    )
    if is_long:
        events["is_home"] = [1, 0]
    events = events.drop(
        columns=["odd_home", "odd_draw", "odd_away"] if missing == "all" else [missing]
    )
    result = evaluate_1x2_betting(
        events,
        pd.Series([1, 0] if is_long else [0]),
        np.array([[0.4, 0.6], [0.8, 0.2]] if is_long else [[0.6, 0.2, 0.2]]),
        is_long=is_long,
        classes=None if is_long else np.array([0, 1, 2]),
        min_edge_threshold=-1,
        flat_stake=10,
        initial_bankroll=1000,
        sweep_thresholds=[-1, 0],
    )
    assert result["n_total_events"] == 1
    assert result["valid_odds_count"] == 0
    assert result["valid_distribution_count"] == 1
    assert set(result["market_metrics"]) == {"logloss", "accuracy", "brier"}
    assert result["n_bets"] == 0
    assert result["coverage"] == 0
    assert not result["bet_trace"]["bet_placed"].any()
    assert result["sweep_df"]["n_bets"].tolist() == [0, 0]
