"""Инкрементальный NHL source: дата последнего матча."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sports_forecast.data.providers.nhl.assembler import (
    AssemblerConfig,
    last_finished_match_date_from_source_csv,
    resolve_incremental_date_from,
)


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
