"""Тест слияния линий в source-подобный DataFrame."""

from __future__ import annotations

import pandas as pd

from sports_forecast.data.providers.odds.enrichment import merge_odds_into_source_dataframe


def test_merge_odds_by_date_and_teams() -> None:
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "id": ["1"],
        }
    )
    odds = pd.DataFrame(
        {
            "game_date": ["2024-01-15"],
            "home_team_norm": ["AAA"],
            "away_team_norm": ["BBB"],
            "pinnacle_home_close": [1.9],
        }
    )
    out = merge_odds_into_source_dataframe(src, odds)
    assert float(out["pinnacle_home_close"].iloc[0]) == 1.9
