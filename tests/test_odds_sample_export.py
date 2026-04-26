"""Сводка нескольких матчей → CSV-колонки (без сети)."""

from __future__ import annotations

from typing import Any

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds.sample_export import (
    bookmaker_keys_from_event,
    events_to_match_sample_dataframe,
)


def _profiles_cfg() -> dict[str, Any]:
    return {
        "bookmaker_profiles": {
            "pinnacle": {
                "key": "pinnacle",
                "winner_semantics": "winner_withOT",
                "total_semantics": "total_withOT",
                "has_draw": False,
            },
            "onexbet": {
                "key": "onexbet",
                "winner_semantics": "winner",
                "total_semantics": "total",
                "has_draw": True,
            },
        }
    }


def _one_event() -> dict[str, Any]:
    return {
        "commence_time": "2024-12-10T19:00:00Z",
        "home_team": "Team Alpha",
        "away_team": "Team Beta",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Team Alpha", "price": 1.7},
                            {"name": "Team Beta", "price": 2.1},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.95, "point": 5.5},
                            {"name": "Under", "price": 1.87, "point": 5.5},
                        ],
                    },
                ],
            },
            {
                "key": "onexbet",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Team Alpha", "price": 1.5},
                            {"name": "Draw", "price": 4.0},
                            {"name": "Team Beta", "price": 2.0},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.8, "point": 4.0},
                            {"name": "Under", "price": 1.9, "point": 4.0},
                        ],
                    },
                ],
            },
        ],
    }


def test_bookmaker_keys_sorted_joined() -> None:
    ev = _one_event()
    assert bookmaker_keys_from_event(ev) == "onexbet|pinnacle"


def test_events_to_match_sample_dataframe_two_rows() -> None:
    ev2 = {
        **_one_event(),
        "home_team": "Gamma",
        "away_team": "Delta",
        "commence_time": "2024-12-11T19:00:00Z",
    }
    cfg = OmegaConf.create(_profiles_cfg())
    df = events_to_match_sample_dataframe([_one_event(), ev2], cfg, team_registry=None, limit=5)
    assert len(df) == 2
    assert df.columns[0] == "bookmakers_in_event"
    assert df["bookmakers_in_event"].iloc[0] == "onexbet|pinnacle"
    assert "pinnacle_winner_withOT_home_close" in df.columns
    assert float(df["pinnacle_winner_withOT_home_close"].iloc[0]) == pytest.approx(1.7)
    assert float(df["onexbet_winner_draw_close"].iloc[0]) == pytest.approx(4.0)


def test_events_to_match_sample_empty() -> None:
    cfg = OmegaConf.create(_profiles_cfg())
    df = events_to_match_sample_dataframe([], cfg, limit=3)
    assert df.empty
