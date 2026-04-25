"""Тест слияния линий в source-подобный DataFrame."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.data.providers.odds.enrichment import (
    BookmakerExtractionProfile,
    _totals_line_and_prices,
    events_to_odds_frame,
    extract_bookmaker_row_from_event,
    extract_pinnacle_row_from_event,
    merge_odds_into_source_dataframe,
)
from sports_forecast.data.providers.odds.store import ODDS_STORE_COLUMNS_V2
from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry


def _minimal_v2_odds_row(
    game_date: str = "2024-01-15",
    home: str = "AAA",
    away: str = "BBB",
) -> dict[str, object | None]:
    row: dict[str, object | None] = dict.fromkeys(ODDS_STORE_COLUMNS_V2, None)
    row["game_date"] = game_date
    row["home_team_norm"] = home
    row["away_team_norm"] = away
    row["commence_time_utc"] = "2024-01-15T20:00:00Z"
    row["open_snapshot_utc"] = "2024-01-14T12:00:00Z"
    row["close_snapshot_utc"] = "2024-01-15T19:00:00Z"
    row["open_minutes_before"] = 1440.0
    row["close_minutes_before"] = 60.0
    row["pinnacle_winner_withOT_home_close"] = 1.95
    row["pinnacle_winner_withOT_away_close"] = 2.05
    row["pinnacle_total_withOT_line_close"] = 5.5
    row["onexbet_winner_home_close"] = 1.88
    row["onexbet_total_line_close"] = 4.0
    row["fetched_at"] = "2024-01-16T00:00:00+00:00"
    return row


def test_merge_v2_store_columns_into_source() -> None:
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "id": ["1"],
        }
    )
    odds = pd.DataFrame([_minimal_v2_odds_row()])
    out = merge_odds_into_source_dataframe(src, odds)
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == pytest.approx(1.95)
    assert out["commence_time_utc"].iloc[0] == "2024-01-15T20:00:00Z"
    assert float(out["onexbet_winner_home_close"].iloc[0]) == pytest.approx(1.88)
    assert float(out["pinnacle_total_withOT_line_close"].iloc[0]) == pytest.approx(5.5)
    assert "commence_time_utc_odds" not in out.columns
    assert "home_team_norm_odds" not in out.columns


def test_merge_v2_replaces_overlapping_source_values_no_suffix_columns() -> None:
    """Поле source с тем же именем, что и в odds, заменяется без дубликатов «*_odds»."""
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "commence_time_utc": ["OLD"],
            "pinnacle_winner_withOT_home_close": [0.0],
        }
    )
    odds = pd.DataFrame([_minimal_v2_odds_row()])
    out = merge_odds_into_source_dataframe(src, odds)
    assert out["commence_time_utc"].iloc[0] == "2024-01-15T20:00:00Z"
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == pytest.approx(1.95)
    assert list(out.columns).count("commence_time_utc") == 1


def test_merge_odds_v1_dataframe_still_works() -> None:
    """Старые имена V1 в odds_df: merge и ключевые поля остаются валидными."""
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
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


def test_merge_odds_with_registry_alias() -> None:
    """Source с длинным именем; odds с каноническими ключами после реестра."""
    reg = TeamNameRegistry.from_source_sections(
        nhl_api={"Long Home Name": "LH", "Away Side": "AS"},
        odds_api={},
    )
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["Long Home Name"],
            "away_team": ["Away Side"],
        }
    )
    odds = pd.DataFrame(
        {
            "game_date": ["2024-01-15"],
            "home_team_norm": ["LH"],
            "away_team_norm": ["AS"],
            "pinnacle_home_close": [2.05],
        }
    )
    out = merge_odds_into_source_dataframe(src, odds, team_registry=reg)
    assert float(out["pinnacle_home_close"].iloc[0]) == 2.05


def test_merge_odds_fallback_without_registry() -> None:
    """Без реестра сопоставление только по normalize_team_key (как раньше)."""
    src = pd.DataFrame(
        {
            "datetime": ["2024-02-01T12:00:00Z"],
            "home_team": ["Team-A"],
            "away_team": ["Team-B"],
        }
    )
    odds = pd.DataFrame(
        {
            "game_date": ["2024-02-01"],
            "home_team_norm": ["TEAMA"],
            "away_team_norm": ["TEAMB"],
            "pinnacle_away_close": [3.1],
        }
    )
    out = merge_odds_into_source_dataframe(src, odds, team_registry=None)
    assert float(out["pinnacle_away_close"].iloc[0]) == 3.1


def test_unmatched_teams_report_written(tmp_path: Path) -> None:
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["H1"],
            "away_team": ["A1"],
        }
    )
    odds = pd.DataFrame(
        {
            "game_date": ["2024-01-15", "2024-01-16"],
            "home_team_norm": ["H1", "ONLYODDS"],
            "away_team_norm": ["A1", "A2"],
        }
    )
    rep = tmp_path / "u.csv"
    merge_odds_into_source_dataframe(
        src,
        odds,
        unmatched_teams_path=rep,
    )
    assert rep.is_file()
    logged = pd.read_csv(rep)
    assert len(logged) == 1
    assert logged.iloc[0]["home_team_norm"] == "ONLYODDS"
    assert logged.iloc[0]["game_date"] == "2024-01-16"


def test_default_unmatched_path_via_tournament(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Параметр ``tournament`` задаёт путь отчёта относительно project_root."""
    from sports_forecast.data.providers.odds import enrichment as enr

    monkeypatch.setattr(enr, "PROJECT_ROOT", tmp_path)
    rep = enr.default_unmatched_teams_report_path("nhl", project_root=tmp_path)
    assert rep == tmp_path / "data" / "source" / "nhl" / "odds" / "unmatched_teams.csv"
    src = pd.DataFrame(
        {
            "datetime": ["2024-01-15T20:00:00Z"],
            "home_team": ["H"],
            "away_team": ["A"],
        }
    )
    odds = pd.DataFrame(
        {
            "game_date": ["2024-01-16"],
            "home_team_norm": ["X"],
            "away_team_norm": ["Y"],
        }
    )
    merge_odds_into_source_dataframe(
        src,
        odds,
        tournament="nhl",
        project_root=tmp_path,
    )
    assert rep.is_file()
    df = pd.read_csv(rep)
    assert len(df) == 1


def test_events_to_odds_frame_uses_registry_for_keys() -> None:
    out_cols: dict = {"moneyline": {}, "total": {}}
    reg = TeamNameRegistry.from_source_sections(
        nhl_api={},
        odds_api={"Odds Long": "OL"},
    )
    ev = [
        {
            "home_team": "Odds Long",
            "away_team": "Away",
            "commence_time": "2024-03-01T18:00:00Z",
            "bookmakers": [],
        }
    ]
    df = events_to_odds_frame(ev, None, "pinnacle", out_cols, team_registry=reg)
    assert df.iloc[0]["home_team_norm"] == "OL"
    assert df.iloc[0]["away_team_norm"] == "AWAY"


def test_totals_line_and_prices_extracts_point_and_over_under() -> None:
    bm = {
        "markets": [
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": 1.95, "point": 5.5},
                    {"name": "Under", "price": 1.86, "point": 5.5},
                ],
            }
        ]
    }
    line, o, u = _totals_line_and_prices(bm)
    assert line == pytest.approx(5.5)
    assert o == pytest.approx(1.95)
    assert u == pytest.approx(1.86)


def _pinnacle_onexbet_single_event() -> list[dict]:
    """Один event с Pinnacle (2-way ML + total) и 1xBet (1X2 + total)."""
    return [
        {
            "home_team": "Team Alpha",
            "away_team": "Team Beta",
            "commence_time": "2024-12-10T00:00:00Z",
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
    ]


def test_events_to_odds_frame_multi_bookmaker_pinnacle_onexbet() -> None:
    profs: dict = {
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
    ev = _pinnacle_onexbet_single_event()
    df = events_to_odds_frame(
        ev, None, "pinnacle", {}, bookmaker_profiles=profs, team_registry=None
    )
    r = df.iloc[0]
    assert r["commence_time_utc"] is not None
    assert "2024-12-10" in r["commence_time_utc"] or "12-10" in (r["commence_time_utc"] or "")
    # Pinnacle full-game semantics
    assert r["pinnacle_winner_withOT_home_open"] == pytest.approx(1.7)
    assert r["pinnacle_winner_withOT_away_open"] == pytest.approx(2.1)
    assert r["pinnacle_total_withOT_line_open"] == pytest.approx(5.5)
    assert r["pinnacle_total_withOT_over_open"] == pytest.approx(1.95)
    assert r["pinnacle_total_withOT_under_open"] == pytest.approx(1.87)
    # 1xBet regulation
    assert r["onexbet_winner_home_open"] == pytest.approx(1.5)
    assert r["onexbet_winner_draw_open"] == pytest.approx(4.0)
    assert r["onexbet_winner_away_open"] == pytest.approx(2.0)
    assert r["onexbet_total_line_open"] == pytest.approx(4.0)
    assert r["onexbet_total_over_open"] == pytest.approx(1.8)
    assert r["onexbet_total_under_open"] == pytest.approx(1.9)


def test_v2_semantics_names_distinct_winner_and_total() -> None:
    p_pin = BookmakerExtractionProfile.from_mapping(
        "pinnacle",
        {"key": "pinnacle", "winner_semantics": "winner_withOT", "total_semantics": "total_withOT"},
    )
    p_1x = BookmakerExtractionProfile.from_mapping(
        "onexbet", {"key": "onexbet", "winner_semantics": "winner", "total_semantics": "total"}
    )
    ev = _pinnacle_onexbet_single_event()[0]
    r1 = extract_bookmaker_row_from_event(ev, p_pin, snapshot_role="open")
    r2 = extract_bookmaker_row_from_event(ev, p_1x, snapshot_role="open")
    assert "pinnacle_winner_withOT_home_open" in r1
    assert "pinnacle_total_withOT_line_open" in r1
    assert "onexbet_winner_home_open" in r2
    assert "onexbet_total_line_open" in r2
    assert "pinnacle_winner_home_open" not in r1
    assert "onexbet_winner_withOT_home_open" not in r2


def test_extract_pinnacle_row_legacy_output_columns_unchanged() -> None:
    out_cols: dict = {
        "moneyline": {
            "home_open": "pinnacle_home_open",
            "away_open": "pinnacle_away_open",
            "draw_open": "pinnacle_draw_open",
            "home_close": "pinnacle_home_close",
            "away_close": "pinnacle_away_close",
            "draw_close": "pinnacle_draw_close",
        },
        "total": {"open": "pinnacle_total_open", "close": "pinnacle_total_close"},
    }
    ev = _pinnacle_onexbet_single_event()[0]
    # только pinnacle в event — берём первого букмекера
    ev_only_pin = {**ev, "bookmakers": [ev["bookmakers"][0]]}
    row = extract_pinnacle_row_from_event(ev_only_pin, "pinnacle", out_cols, snapshot_role="single")
    assert row["pinnacle_home_open"] == pytest.approx(1.7)
    assert row["pinnacle_away_open"] == pytest.approx(2.1)
    assert row["pinnacle_total_open"] == pytest.approx(1.95)
    assert row["pinnacle_total_close"] == pytest.approx(1.95)


def test_totals_line_uses_market_level_point() -> None:
    """``point`` на рынке ``totals`` (не только в outcomes) задаёт line."""
    bm = {
        "markets": [
            {
                "key": "totals",
                "point": 6.0,
                "outcomes": [
                    {"name": "Over", "price": 1.9},
                    {"name": "Under", "price": 1.85},
                ],
            }
        ]
    }
    line, o, u = _totals_line_and_prices(bm)
    assert line == pytest.approx(6.0)
    assert o == pytest.approx(1.9)
    assert u == pytest.approx(1.85)


def test_pinnacle_v2_has_draw_false_draw_columns_nan_for_2way_h2h() -> None:
    """2-way h2h без Draw: draw-колонки Pinnacle V2 пустые (R21.3/tech-debt)."""
    profs: dict = {
        "pinnacle": {
            "key": "pinnacle",
            "winner_semantics": "winner_withOT",
            "total_semantics": "total_withOT",
            "has_draw": False,
        },
    }
    ev = _pinnacle_onexbet_single_event()
    # только Pinnacle (2-way)
    ev_pin = [{**ev[0], "bookmakers": [ev[0]["bookmakers"][0]]}]
    df = events_to_odds_frame(
        ev_pin, None, "pinnacle", {}, bookmaker_profiles=profs, team_registry=None
    )
    r = df.iloc[0]
    assert pd.isna(r["pinnacle_winner_withOT_draw_open"])
    assert pd.isna(r["pinnacle_winner_withOT_draw_close"])


def test_events_to_odds_frame_legacy_no_profiles_same_pinnacle_values() -> None:
    out_cols: dict = {
        "moneyline": {
            "home_open": "pinnacle_home_open",
            "away_open": "pinnacle_away_open",
            "draw_open": "pinnacle_draw_open",
            "home_close": "pinnacle_home_close",
            "away_close": "pinnacle_away_close",
            "draw_close": "pinnacle_draw_close",
        },
        "total": {"open": "pinnacle_total_open", "close": "pinnacle_total_close"},
    }
    ev = _pinnacle_onexbet_single_event()
    # без bookmaker_profiles: один primary (pinnacle), старые имена
    df = events_to_odds_frame(
        ev, None, "pinnacle", out_cols, bookmaker_profiles=None, book_cfg=None
    )
    r = df.iloc[0]
    assert r["pinnacle_home_open"] == pytest.approx(1.7)
    assert "commence_time_utc" in df.columns
    assert "pinnacle_winner_withOT_home_open" not in df.columns
