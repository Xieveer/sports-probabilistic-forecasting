"""Тест слияния линий в source-подобный DataFrame."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.data.providers.odds.enrichment import (
    events_to_odds_frame,
    merge_odds_into_source_dataframe,
)
from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry


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
