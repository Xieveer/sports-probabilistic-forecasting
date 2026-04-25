"""Инкрементальный NHL source: дата последнего матча."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sports_forecast.data.providers.nhl.assembler import (
    AssemblerConfig,
    _merge_full_source_snapshot,
    last_finished_match_date_from_source_csv,
    resolve_incremental_date_from,
)
from sports_forecast.data.providers.nhl.schedule import ScheduleGameStub


def test_last_finished_match_date_from_csv(tmp_path: Path) -> None:
    p = tmp_path / "source.csv"
    p.write_text(
        "datetime,match_is_end\n"
        "2024-01-01T20:00:00Z,1\n"
        "2024-01-10T20:00:00Z,1\n"
        "2024-02-01T20:00:00Z,0\n",
        encoding="utf-8",
    )
    d = last_finished_match_date_from_source_csv(p)
    assert d == date(2024, 1, 10)


def test_resolve_incremental_adjusts_date_from(tmp_path: Path) -> None:
    p = tmp_path / "source.csv"
    p.write_text("datetime,match_is_end\n2024-03-15T20:00:00Z,1\n", encoding="utf-8")
    base = AssemblerConfig(
        date_from=date(2020, 1, 1),
        date_to=date(2025, 1, 1),
        season_id_min=None,
        season_id_max=None,
        max_games=None,
        include_play_by_play=True,
        finished_only=True,
        roster_enabled=True,
        checkpoint_file=None,
        progress_log_every=0,
        schedule_progress_file=None,
        csv_flush_every=0,
        incremental=True,
        incremental_buffer_days=3,
    )
    adj = resolve_incremental_date_from(base, p)
    assert adj.date_from == date(2024, 3, 12)


def test_merge_full_source_snapshot_keeps_history_outside_window() -> None:
    """Инкремент: строки вне окна расписания остаются; окно заменяется."""
    prev = {
        "1": {"id": "1", "datetime": "2020-01-01T20:00:00Z", "match_is_end": "1"},
        "2": {"id": "2", "datetime": "2024-01-01T20:00:00Z", "match_is_end": "1"},
    }
    stub = ScheduleGameStub(
        game_id=2,
        season=2024,
        game_type=2,
        game_date="2024-01-01",
        start_time_utc="2024-01-01T20:00:00Z",
        venue_default="X",
        home_abbrev="A",
        away_abbrev="B",
        game_state="OFF",
        match_end="REG",
        home_score=3,
        away_score=2,
    )
    new_row = {
        "id": "2",
        "datetime": "2024-01-01T20:00:00Z",
        "match_is_end": "1",
        "home_score_ft": "3",
    }
    merged, n_ret, n_win = _merge_full_source_snapshot([stub], [new_row], prev)
    assert n_ret == 1
    assert n_win == 1
    assert len(merged) == 2
    by_id = {str(r["id"]): r for r in merged}
    assert by_id["1"]["id"] == "1"
    assert by_id["2"]["home_score_ft"] == "3"
