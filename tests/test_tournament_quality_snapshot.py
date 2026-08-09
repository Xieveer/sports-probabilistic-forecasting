"""Тесты сохранения нормализованного расписания для tournament quality gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from sports_forecast.validation.tournament_quality import (
    TournamentQualityGateConfig,
    load_schedule_coverage,
    load_schedule_snapshot,
    save_schedule_snapshot,
    schedule_snapshot_path,
)


def _config() -> TournamentQualityGateConfig:
    return TournamentQualityGateConfig(
        tournament="test_league",
        schedule_window_hours=48,
        required_result_fields=("home_score", "away_score"),
        schedule_snapshot_filename="quality_schedule.csv",
    )


def test_snapshot_roundtrip_keeps_only_normalized_schedule_fields(tmp_path) -> None:
    config = _config()
    source_csv = tmp_path / "source.csv"
    rows = pd.DataFrame(
        [
            {
                "id": "42",
                "datetime": "2026-08-08T09:00:00Z",
                "game_state": "FUT",
                "untrusted_raw_payload": "secret-value",
            }
        ]
    )

    path = schedule_snapshot_path(source_csv, config)
    covered_until = datetime(2026, 8, 10, 9, tzinfo=UTC)
    save_schedule_snapshot(rows, path, config, covered_until=covered_until)
    loaded = load_schedule_snapshot(path, config)

    assert path == tmp_path / "quality_schedule.csv"
    assert list(loaded.columns) == ["id", "datetime", "game_state"]
    assert loaded.to_dict(orient="records") == [
        {"id": "42", "datetime": "2026-08-08T09:00:00Z", "game_state": "FUT"}
    ]
    assert "secret-value" not in path.read_text(encoding="utf-8")
    assert load_schedule_coverage(source_csv, config) == covered_until
