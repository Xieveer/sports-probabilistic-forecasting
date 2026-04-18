"""Тесты NHL schedule / standings пре-генераторов."""

from __future__ import annotations

import pandas as pd

from sports_forecast.features.generators.schedule_generator import NhlScheduleFeatureGenerator
from sports_forecast.features.generators.standings_generator import NhlStandingsFeatureGenerator


def test_nhl_schedule_generator_basic() -> None:
    cfg = {
        "type": "nhl_schedule",
        "datetime_column": "datetime",
        "required_columns": ["home_team", "away_team", "datetime", "home_sog_ft"],
    }
    gen = NhlScheduleFeatureGenerator(cfg)
    df = pd.DataFrame(
        {
            "home_team": ["A", "A", "B"],
            "away_team": ["B", "C", "C"],
            "datetime": pd.to_datetime(
                [
                    "2024-01-01 19:00:00+00:00",
                    "2024-01-03 19:00:00+00:00",
                    "2024-01-02 19:00:00+00:00",
                ]
            ),
            "home_sog_ft": [30.0, 31.0, 29.0],
        }
    )
    out = gen.generate(df)
    assert "rest_advantage" in out.columns
    assert out["home_games_in_last_7d"].notna().all()


def test_nhl_standings_skips_without_columns() -> None:
    cfg = {"type": "nhl_standings"}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "datetime": [pd.Timestamp.utcnow()]})
    out = gen.generate(df)
    assert "conf_rank_diff" not in out.columns
