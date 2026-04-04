"""Тесты NHL Web API провайдера (без сетевых вызовов)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.data.providers import NhlWebApiSourceProvider, get_provider
from sports_forecast.data.providers.nhl.boxscore import aggregate_play_by_play, build_team_stats
from sports_forecast.data.providers.nhl.schedule import _parse_game
from sports_forecast.data.providers.nhl.standings import parse_standings_payload


def test_parse_game_without_game_date_uses_fallback() -> None:
    g = {
        "id": 1999020607,
        "season": 19992000,
        "gameType": 2,
        "startTimeUTC": "2000-01-15T18:00:00Z",
        "venue": {"default": "Old Arena"},
        "homeTeam": {"abbrev": {"default": "NYR"}},
        "awayTeam": {"abbrev": {"default": "BOS"}},
        "gameState": "OFF",
    }
    stub = _parse_game(g, fallback_game_date="2000-01-15")
    assert stub is not None
    assert stub.game_id == 1999020607
    assert stub.game_date == "2000-01-15"


def test_aggregate_play_by_play_counts_regulation_goal() -> None:
    pbp = {
        "plays": [
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 2, "periodType": "REG", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 4, "periodType": "OT", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
        ]
    }
    h, a = aggregate_play_by_play(pbp, home_id=10, away_id=20)
    assert h.score_mt == 1
    assert a.score_mt == 0
    assert h.score_ft is None  # выставляется из boxscore


def test_aggregate_play_by_play_minor_penalty_2pim() -> None:
    pbp = {
        "plays": [
            {
                "typeDescKey": "penalty",
                "periodDescriptor": {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10, "typeCode": "MIN", "duration": 2},
            },
            {
                "typeDescKey": "penalty",
                "periodDescriptor": {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 20, "typeCode": "MIN", "duration": 5},
            },
        ]
    }
    h, a = aggregate_play_by_play(pbp, home_id=10, away_id=20)
    assert h.pim_ft == 2
    assert h.pim2_ft == 2
    assert a.pim_ft == 5
    assert a.pim2_ft == 0


def test_build_team_stats_without_pbp_uses_skater_totals() -> None:
    box = {
        "homeTeam": {"id": 1, "score": 3, "sog": 30},
        "awayTeam": {"id": 2, "score": 1, "sog": 20},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{"blockedShots": 2, "hits": 3, "pim": 2}],
                "defense": [{"blockedShots": 1, "hits": 0, "pim": 0}],
                "goalies": [],
            },
            "awayTeam": {
                "forwards": [{"blockedShots": 1, "hits": 1, "pim": 0}],
                "defense": [],
                "goalies": [],
            },
        },
    }
    zh, za, hid, aid = build_team_stats(box, None)
    assert hid == 1
    assert aid == 2
    assert zh.score_ft == 3
    assert za.score_ft == 1
    assert zh.bs_ft == 3
    assert za.bs_ft == 1


def test_parse_standings_payload_team_abbrev() -> None:
    payload = {
        "standings": [
            {
                "teamAbbrev": {"default": "COL"},
                "conferenceAbbrev": "C",
                "conferenceSequence": 3,
                "points": 90,
                "gamesPlayed": 70,
            }
        ]
    }
    idx = parse_standings_payload(payload)
    assert idx["COL"].conference_rank == 3
    assert idx["COL"].points == 90


def test_get_provider_nhl_web_api() -> None:
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    source_cfg = OmegaConf.create(
        {
            "provider": {
                "type": "nhl_web_api",
                "date_from": "2020-01-01",
                "date_to": "2020-01-01",
                "max_games": 0,
                "roster_enabled": False,
            }
        }
    )
    p = get_provider(source_cfg, paths_cfg)
    assert isinstance(p, NhlWebApiSourceProvider)


@patch("sports_forecast.data.providers.nhl.provider.NhlDataAssembler.build_dataframe")
def test_nhl_provider_fetch_writes_csv(mock_build: MagicMock, tmp_path: Path) -> None:
    mock_build.return_value = pd.DataFrame(
        [
            {
                "id": "1",
                "nhl_id": "1",
                "season": "20252026",
                "game_type": "regular",
                "datetime": "2026-03-30T23:00:00Z",
                "location": "Test Arena",
                "home_team": "NYI",
                "away_team": "PIT",
                "match_end": "REG",
                "match_is_end": "1",
            }
        ]
    )
    paths_cfg = OmegaConf.create({"paths": {"source_dir": str(tmp_path / "src")}})
    source_cfg = OmegaConf.create({"provider": {"type": "nhl_web_api", "max_games": 1}})
    prov = NhlWebApiSourceProvider(
        source_cfg=source_cfg, paths_cfg=paths_cfg, project_root=tmp_path
    )
    out = prov.fetch("nhl")
    assert out.exists()
    df = pd.read_csv(out)
    assert len(df) == 1
    assert df.iloc[0]["home_team"] == "NYI"
