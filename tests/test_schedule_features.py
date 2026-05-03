"""Тесты NHL schedule / standings пре-генераторов."""

from __future__ import annotations

from typing import cast

import pandas as pd

from sports_forecast.features.generators.schedule_generator import NhlScheduleFeatureGenerator
from sports_forecast.features.generators.standings_generator import NhlStandingsFeatureGenerator


def test_nhl_schedule_generator_basic() -> None:
    cfg = {
        "type": "nhl_schedule",
        "datetime_column": "datetime",
        "required_columns": ["home_team", "away_team", "datetime", "home_sog_ft"],
        "travel": {"enabled": False},
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
    assert "home_km_since_last_game" not in out.columns


def test_nhl_schedule_travel_features_coast_to_coast() -> None:
    """NYR (MSG) → LAK (Crypto): большой перелёт для гостей между играми."""
    cfg = {
        "type": "nhl_schedule",
        "datetime_column": "datetime",
        "required_columns": ["home_team", "away_team", "datetime", "home_sog_ft"],
        "travel": {"enabled": True},
    }
    gen = NhlScheduleFeatureGenerator(cfg)
    df = pd.DataFrame(
        {
            "home_team": ["NYR", "LAK"],
            "away_team": ["LAK", "NYR"],
            "datetime": pd.to_datetime(
                [
                    "2024-01-01 00:00:00+00:00",
                    "2024-01-05 03:00:00+00:00",
                ]
            ),
            "home_sog_ft": [28.0, 30.0],
        }
    )
    out = gen.generate(df)
    assert "home_km_since_last_game" in out.columns
    # Вторая строка: дома LAK, гости NYR; у NYR предыдущая площадка — NYR (играли в гостях у NYR дома MSG)
    raw_km = out.iloc[1]["away_km_since_last_game"]
    assert raw_km is not None and pd.notna(raw_km)
    assert cast(float, raw_km) > 3500.0
    raw_tz = out.iloc[1]["away_tz_shift_since_last"]
    assert raw_tz is not None and pd.notna(raw_tz)
    tz_away = cast(float, raw_tz)
    # Предыдущая площадка NYR — MSG (-5), текущая — Лос-Анджелес (-8)
    assert tz_away == -3.0


def test_nhl_standings_skips_without_columns() -> None:
    cfg = {"type": "nhl_standings"}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "datetime": [pd.Timestamp.utcnow()]})
    out = gen.generate(df)
    assert "conf_rank_diff" not in out.columns
