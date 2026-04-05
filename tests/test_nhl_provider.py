"""Тесты NHL Web API провайдера (без сетевых вызовов)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.data.providers import NhlWebApiSourceProvider, get_provider
from sports_forecast.data.providers.nhl.assembler import (
    _build_upcoming_row,
    _load_previous_source_rows,
    _row_is_finished_in_csv,
)
from sports_forecast.data.providers.nhl.boxscore import aggregate_play_by_play, build_team_stats
from sports_forecast.data.providers.nhl.schedule import (
    ScheduleGameStub,
    _parse_game,
    load_schedule_progress,
    save_schedule_progress,
    stub_from_dict,
    stub_to_dict,
)
from sports_forecast.data.providers.nhl.standings import (
    parse_standings_payload,
    standings_snapshot_ymd_before_game_date,
)


def test_schedule_stub_roundtrip_dict() -> None:
    stub = ScheduleGameStub(
        game_id=1,
        season=20002001,
        game_type=2,
        game_date="2000-10-20",
        start_time_utc="2000-10-20T23:00:00Z",
        venue_default="X",
        home_abbrev="AAA",
        away_abbrev="BBB",
        game_state="OFF",
        match_end="REG",
        home_score=2,
        away_score=1,
    )
    d = stub_to_dict(stub)
    back = stub_from_dict(d)
    assert back == stub


def test_schedule_progress_save_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "prog.json"
    d0, d1 = date(2000, 9, 1), date(2000, 11, 1)
    stub = ScheduleGameStub(
        game_id=99,
        season=20002001,
        game_type=2,
        game_date="2000-10-01",
        start_time_utc="2000-10-01T23:00:00Z",
        venue_default="",
        home_abbrev="NYR",
        away_abbrev="BOS",
        game_state="OFF",
        match_end=None,
        home_score=None,
        away_score=None,
    )
    save_schedule_progress(
        p,
        by_id={99: stub},
        next_anchor=date(2000, 10, 27),
        date_from=d0,
        date_to=d1,
        season_min=20002001,
        season_max=None,
        finished_only=True,
        schedule_complete=False,
    )
    loaded = load_schedule_progress(
        p,
        date_from=d0,
        date_to=d1,
        season_min=20002001,
        season_max=None,
        finished_only=True,
    )
    assert loaded is not None
    by_id, resume, complete = loaded
    assert not complete
    assert resume == date(2000, 10, 27)
    assert by_id[99].game_id == 99


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
    # Гол в основное время учитывается как бросок (часто нет отдельного shot-on-goal).
    assert h.sog_mt == 1
    assert a.sog_mt == 0
    # ОТ-гол в SOG за матч, не в mt; буллит в этом тесте нет.
    assert h.sog_ft == 2
    assert a.sog_ft == 0


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


def test_aggregate_play_by_play_excludes_shootout_from_sog_ft() -> None:
    """Буллит не входит в официальные team SOG: не считаем shot-on-goal периода SO."""
    pbp = {
        "plays": [
            {
                "typeDescKey": "shot-on-goal",
                "periodDescriptor": {"number": 5, "periodType": "SO", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
            {
                "typeDescKey": "goal",
                "periodDescriptor": {"number": 5, "periodType": "SO", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
        ]
    }
    h, a = aggregate_play_by_play(pbp, home_id=10, away_id=20)
    assert h.sog_ft == 0
    assert h.sog_mt == 0
    assert a.sog_ft == 0


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


def test_build_team_stats_with_pbp_bs_ft_from_boxscore_skaters() -> None:
    """При включённом PBP официальные blocked shots — сумма скейтеров, не счётчик PBP."""
    box = {
        "homeTeam": {"id": 10, "score": 1, "sog": 10},
        "awayTeam": {"id": 20, "score": 1, "sog": 9},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{"blockedShots": 5, "hits": 0, "pim": 0}],
                "defense": [],
                "goalies": [],
            },
            "awayTeam": {
                "forwards": [{"blockedShots": 2, "hits": 0, "pim": 0}],
                "defense": [],
                "goalies": [],
            },
        },
    }
    pbp = {
        "plays": [
            {
                "typeDescKey": "blocked-shot",
                "periodDescriptor": {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
            {
                "typeDescKey": "blocked-shot",
                "periodDescriptor": {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3},
                "details": {"eventOwnerTeamId": 10},
            },
        ]
    }
    zh, za, _, _ = build_team_stats(box, pbp)
    assert zh.bs_ft == 5
    assert za.bs_ft == 2
    assert zh.bs_mt == 2
    assert za.bs_mt == 0


def test_row_is_finished_in_csv() -> None:
    assert _row_is_finished_in_csv({"match_is_end": "1"})
    assert not _row_is_finished_in_csv({"match_is_end": "0"})
    assert not _row_is_finished_in_csv({})


def test_build_upcoming_row_match_is_end_zero() -> None:
    stub = ScheduleGameStub(
        game_id=9,
        season=20252026,
        game_type=2,
        game_date="2025-12-01",
        start_time_utc="2025-12-01T20:00:00Z",
        venue_default="X",
        home_abbrev="EDM",
        away_abbrev="CGY",
        game_state="FUT",
        match_end=None,
        home_score=None,
        away_score=None,
    )
    row = _build_upcoming_row(stub, st_idx={}, include_pbp=True)
    assert row["match_is_end"] == "0"
    assert row["home_score_ft"] == ""
    assert row["id"] == "9"


def test_load_previous_source_rows(tmp_path: Path) -> None:
    p = tmp_path / "source.csv"
    pd.DataFrame([{"id": "1", "match_is_end": "1", "home_team": "A"}]).to_csv(p, index=False)
    got = _load_previous_source_rows(p)
    assert got["1"]["home_team"] == "A"


def test_standings_snapshot_ymd_before_game_date() -> None:
    assert standings_snapshot_ymd_before_game_date("2025-10-08") == "2025-10-07"
    assert standings_snapshot_ymd_before_game_date("2000-01-01") == "1999-12-31"


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
    df_one = pd.DataFrame(
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

    def _fake_build(
        *,
        checkpoint_base: Path | None = None,
        output_csv_path: Path | None = None,
    ) -> pd.DataFrame:
        if output_csv_path is not None:
            df_one.to_csv(output_csv_path, index=False)
        return df_one

    mock_build.side_effect = _fake_build
    paths_cfg = OmegaConf.create({"paths": {"source_dir": str(tmp_path / "src")}})
    source_cfg = OmegaConf.create({"provider": {"type": "nhl_web_api", "max_games": 1}})
    prov = NhlWebApiSourceProvider(
        source_cfg=source_cfg, paths_cfg=paths_cfg, project_root=tmp_path
    )
    out = prov.fetch("nhl")
    mock_build.assert_called_once()
    assert mock_build.call_args.kwargs.get("output_csv_path") == out
    assert out.exists()
    df = pd.read_csv(out)
    assert len(df) == 1
    assert df.iloc[0]["home_team"] == "NYI"
