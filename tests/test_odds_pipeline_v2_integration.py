"""Сквозной мини-поток R21: JSON как из API → enrichment V2 → store → merge в source (R21.8)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds.enrichment import (
    events_to_odds_frame,
    merge_odds_into_source_csv,
)
from sports_forecast.data.providers.odds.store import load_odds_store, save_odds_store


def _book_cfg_v2() -> dict:
    return {
        "bookmakers": {"primary": "pinnacle"},
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
        },
        "output_columns": {
            "moneyline": {
                "home_open": "pinnacle_home_open",
                "away_open": "pinnacle_away_open",
            },
            "total": {"open": "pinnacle_total_open", "close": "pinnacle_total_close"},
        },
    }


def _api_event_tampa_boston() -> list[dict]:
    """Как в ответе The Odds API: два букмекера, h2h + totals (mock payload)."""
    return [
        {
            "home_team": "Tampa Bay Lightning",
            "away_team": "Boston Bruins",
            "commence_time": "2024-12-10T00:00:00Z",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Tampa Bay Lightning", "price": 1.72},
                                {"name": "Boston Bruins", "price": 2.12},
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
                                {"name": "Tampa Bay Lightning", "price": 1.5},
                                {"name": "Draw", "price": 4.0},
                                {"name": "Boston Bruins", "price": 2.0},
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
    ]


def test_end_to_end_mock_backfill_store_v2_merge_source_csv(
    tmp_path: Path,
) -> None:
    """``events_to_odds_frame`` (тот же путь, что backfill по данным) → store → merge в CSV."""
    ev_open = _api_event_tampa_boston()
    ev_close = _api_event_tampa_boston()
    out = events_to_odds_frame(
        ev_open,
        ev_close,
        "pinnacle",
        {},
        book_cfg=OmegaConf.create(_book_cfg_v2()),
        team_registry=None,
    )
    out = out.copy()
    out["open_snapshot_utc"] = "2024-12-09T00:00:00Z"
    out["close_snapshot_utc"] = "2024-12-09T23:00:00Z"
    out["open_minutes_before"] = 1440.0
    out["close_minutes_before"] = 60.0
    if "fetched_at" in out.columns:
        out["fetched_at"] = "2024-12-10T12:00:00+00:00"
    assert out.shape[0] == 1
    sp = tmp_path / "pinnacle_odds.parquet"
    save_odds_store(out, sp)
    loaded = load_odds_store(sp)
    assert "pinnacle_winner_withOT_home_close" in loaded.columns
    assert "onexbet_winner_draw_close" in loaded.columns
    assert float(loaded["pinnacle_total_withOT_line_open"].iloc[0]) == pytest.approx(5.5)

    src_path = tmp_path / "source.csv"
    src_path.write_text(
        "id,datetime,home_team,away_team\n"
        "g1,2024-12-10T00:00:00+00:00,Tampa Bay Lightning,Boston Bruins\n",
        encoding="utf-8",
    )
    merge_odds_into_source_csv(str(src_path), loaded, out_csv_path=str(src_path))
    merged = pd.read_csv(src_path, low_memory=False)
    assert merged.shape[0] == 1
    assert "pinnacle_winner_withOT_home_open" in merged.columns
    assert "onexbet_total_line_open" in merged.columns
    assert float(merged["pinnacle_total_withOT_over_open"].iloc[0]) == pytest.approx(1.95)
    assert float(merged["onexbet_winner_draw_open"].iloc[0]) == pytest.approx(4.0)
    assert str(merged["commence_time_utc"].iloc[0]) == "2024-12-10T00:00:00Z"
