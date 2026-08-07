"""Run-scoped watermark для heavy path tournament quality gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from sports_forecast.orchestration.tournament_quality_watermark import (
    load_watermark,
    save_pre_refresh_watermark,
)
from sports_forecast.validation.tournament_quality import TournamentQualityGateConfig


def test_watermark_keeps_last_completed_match_from_before_refresh(tmp_path) -> None:
    """Новый completed match после refresh не заменяет watermark того же DAG run."""
    config = TournamentQualityGateConfig(
        tournament="demo",
        schedule_window_hours=48,
        required_result_fields=("home_score", "away_score"),
    )
    source_path = tmp_path / "source.csv"
    state_path = tmp_path / "watermark.json"
    pd.DataFrame(
        [
            {
                "id": "old",
                "datetime": "2026-08-07T08:00:00Z",
                "match_is_end": "1",
            }
        ]
    ).to_csv(source_path, index=False)

    save_pre_refresh_watermark(source_path, state_path, config)

    pd.DataFrame(
        [
            {
                "id": "old",
                "datetime": "2026-08-07T08:00:00Z",
                "match_is_end": "1",
            },
            {
                "id": "new",
                "datetime": "2026-08-07T09:00:00Z",
                "match_is_end": "1",
            },
        ]
    ).to_csv(source_path, index=False)

    assert load_watermark(state_path) == datetime(2026, 8, 7, 8, tzinfo=UTC)
