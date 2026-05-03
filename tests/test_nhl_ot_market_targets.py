"""Тесты NHL R22.8: таргеты full match vs regulation (target_sources)."""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import DictConfig

from sports_forecast.features.long_format import wide_to_long
from sports_forecast.utils.targets import compute_target_from_market_spec


@pytest.fixture
def tournament_ice_hockey_ot_sources() -> DictConfig:
    """Минимальный target_sources как в conf/sport/ice_hockey.yaml (фрагмент)."""
    return DictConfig(
        {
            "name": "nhl",
            "target_sources": {
                "player_win_full": {
                    "format": "long",
                    "player_column": "pl_goals_full",
                    "opponent_column": "opp_goals_full",
                    "comparison": "greater",
                },
                "player_win_reg": {
                    "format": "long",
                    "player_column": "pl_goals_reg",
                    "opponent_column": "opp_goals_reg",
                    "comparison": "greater",
                },
                "total_sum_full": {
                    "format": "wide",
                    "home_column": "home_goals_full",
                    "away_column": "away_goals_full",
                    "comparison": "total_over",
                },
                "total_sum": {
                    "format": "wide",
                    "home_column": "home_points",
                    "away_column": "away_points",
                    "comparison": "total_over",
                },
            },
        }
    )


def test_player_win_full_vs_reg_differs_in_ot_scenario(
    tournament_ice_hockey_ot_sources: DictConfig,
) -> None:
    """При ничьей в регламенте и победе в ОТ full-таргет ≠ reg-таргет."""
    wide = pd.DataFrame(
        {
            "id": [1],
            "datetime": pd.to_datetime(["2024-11-01"]),
            "home_team": ["H"],
            "away_team": ["A"],
            "home_points": [4.0],
            "away_points": [3.0],
            "home_goals_reg": [3.0],
            "away_goals_reg": [3.0],
            "home_goals_full": [4.0],
            "away_goals_full": [3.0],
        }
    )
    long_df = wide_to_long(wide, context_columns=[])

    spec_full = DictConfig(
        {
            "name": "winner_withOT",
            "target_source_key": "player_win_full",
            "data_format": "long",
        }
    )
    spec_reg = DictConfig(
        {
            "name": "winner_reg",
            "target_source_key": "player_win_reg",
            "data_format": "long",
        }
    )

    t_full = compute_target_from_market_spec(long_df, spec_full, tournament_ice_hockey_ot_sources)
    t_reg = compute_target_from_market_spec(long_df, spec_reg, tournament_ice_hockey_ot_sources)

    home_row = long_df["side"] == "h"
    # Full match: home wins 4–3
    assert int(t_full.loc[home_row].iloc[0]) == 1
    # Regulation: 3–3 tie → not a strict win by > on goals (3 > 3 is false)
    assert int(t_reg.loc[home_row].iloc[0]) == 0


def test_total_sum_full_matches_total_when_points_equal_goals_full(
    tournament_ice_hockey_ot_sources: DictConfig,
) -> None:
    """При home_goals_full == home_points тотал over совпадает с legacy total_sum."""
    wide = pd.DataFrame(
        {
            "home_points": [4.0, 2.0],
            "away_points": [3.0, 1.0],
            "home_goals_full": [4.0, 2.0],
            "away_goals_full": [3.0, 1.0],
        }
    )
    line = 6.5
    spec_full = DictConfig(
        {
            "name": "total_over_withOT",
            "target_source_key": "total_sum_full",
            "data_format": "wide",
            "line": line,
        }
    )
    spec_legacy = DictConfig(
        {
            "name": "total_over",
            "target_source_key": "total_sum",
            "data_format": "wide",
            "line": line,
        }
    )
    t_full = compute_target_from_market_spec(
        wide, spec_full, tournament_ice_hockey_ot_sources, line=line
    )
    t_legacy = compute_target_from_market_spec(
        wide, spec_legacy, tournament_ice_hockey_ot_sources, line=line
    )
    pd.testing.assert_series_equal(t_full, t_legacy)


def test_wide_to_long_exposes_pl_goals_reg_and_pl_goals_full() -> None:
    """Пары home_goals_* / away_goals_* попадают в long как pl_* / opp_*."""
    wide = pd.DataFrame(
        {
            "id": [1],
            "datetime": pd.to_datetime(["2024-01-02"]),
            "home_team": ["X"],
            "away_team": ["Y"],
            "home_goals_reg": [2.0],
            "away_goals_reg": [1.0],
            "home_goals_full": [3.0],
            "away_goals_full": [1.0],
        }
    )
    long_df = wide_to_long(wide, context_columns=[])
    h = long_df[long_df["side"] == "h"].iloc[0]
    a = long_df[long_df["side"] == "a"].iloc[0]
    assert h["pl_goals_reg"] == 2.0 and h["opp_goals_reg"] == 1.0
    assert h["pl_goals_full"] == 3.0 and h["opp_goals_full"] == 1.0
    assert a["pl_goals_reg"] == 1.0 and a["opp_goals_reg"] == 2.0
