"""Контракт ставки по максимальному edge для одного матча 1X2."""

import numpy as np
import pandas as pd

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
