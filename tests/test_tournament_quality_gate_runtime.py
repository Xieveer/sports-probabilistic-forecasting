"""Runtime wiring сохранённого snapshot в tournament quality gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from sports_forecast.orchestration.tournament_quality_gate_cli import (
    run_tournament_quality_gate,
)
from sports_forecast.orchestration.tournament_quality_watermark import (
    load_watermark,
    save_pre_refresh_watermark,
)
from sports_forecast.validation.tournament_quality import (
    ResultFieldRule,
    TournamentQualityGateConfig,
    save_schedule_snapshot,
    schedule_snapshot_path,
)


def test_runtime_gate_uses_pre_refresh_watermark_after_new_completed_match(tmp_path) -> None:
    """Heavy flow не заменяет watermark новой completed строкой из refresh."""
    config = TournamentQualityGateConfig(
        tournament="demo",
        schedule_window_hours=48,
        required_result_fields=("home_score", "away_score", "match_end"),
        result_field_rules={
            "home_score": ResultFieldRule(value_type="integer", minimum=0, maximum=99),
            "away_score": ResultFieldRule(value_type="integer", minimum=0, maximum=99),
            "match_end": ResultFieldRule(value_type="enum", allowed_values=("REG", "OT", "SO")),
        },
        schedule_snapshot_filename="demo_schedule.csv",
    )
    source_path = tmp_path / "source.csv"
    watermark_path = tmp_path / "watermark.json"
    pd.DataFrame(
        [
            {
                "id": "finished-1",
                "datetime": "2026-08-07T08:00:00Z",
                "match_is_end": "1",
                "home_score": "3",
                "away_score": "2",
                "match_end": "REG",
            },
        ]
    ).to_csv(source_path, index=False)
    save_pre_refresh_watermark(source_path, watermark_path, config)
    pd.DataFrame(
        [
            {
                "id": "finished-1",
                "datetime": "2026-08-07T08:00:00Z",
                "match_is_end": "1",
                "home_score": "3",
                "away_score": "2",
                "match_end": "REG",
            },
            {
                "id": "new-finished-1",
                "datetime": "2026-08-07T09:00:00Z",
                "match_is_end": "1",
                "home_score": "4",
                "away_score": "1",
                "match_end": "REG",
            },
            {
                "id": "upcoming-1",
                "datetime": "2026-08-07T13:00:00Z",
                "match_is_end": "0",
                "home_score": "",
                "away_score": "",
                "match_end": "",
            },
        ]
    ).to_csv(source_path, index=False)
    save_schedule_snapshot(
        pd.DataFrame(
            [
                {"id": "finished-1", "datetime": "2026-08-07T08:00:00Z", "game_state": "OFF"},
                {"id": "new-finished-1", "datetime": "2026-08-07T09:00:00Z", "game_state": "OFF"},
                {"id": "upcoming-1", "datetime": "2026-08-07T13:00:00Z", "game_state": "FUT"},
            ]
        ),
        schedule_snapshot_path(source_path, config),
        config,
        covered_until=datetime(2026, 8, 9, 10, tzinfo=UTC),
    )

    result = run_tournament_quality_gate(
        source_csv_path=source_path,
        config=config,
        refreshed_at=datetime(2026, 8, 7, 10, tzinfo=UTC),
        last_completed_at=load_watermark(watermark_path),
    )

    assert result.is_valid
    assert result.stats == {"schedule_matches": 1, "completed_matches": 2}
