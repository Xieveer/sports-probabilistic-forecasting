"""Контрактные тесты турнир-нейтрального gate полноты source-данных."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from sports_forecast.config.loaders import load_tournament_quality_gate_config
from sports_forecast.validation.tournament_quality import (
    ResultFieldRule,
    TournamentQualityGateConfig,
    validate_tournament_quality_gate,
)


def _config() -> TournamentQualityGateConfig:
    return TournamentQualityGateConfig(
        tournament="test_league",
        schedule_window_hours=48,
        required_result_fields=("home_points", "away_points", "match_end"),
        result_field_rules={
            "home_points": ResultFieldRule(value_type="integer", minimum=0, maximum=100),
            "away_points": ResultFieldRule(value_type="integer", minimum=0, maximum=100),
            "match_end": ResultFieldRule(value_type="enum", allowed_values=("REG", "OT", "SO")),
        },
    )


def _schedule() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"id": "finished-1", "datetime": "2026-08-07T08:00:00Z", "game_state": "OFF"},
            {"id": "upcoming-1", "datetime": "2026-08-08T09:00:00Z", "game_state": "FUT"},
        ]
    )


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": "finished-1",
                "datetime": "2026-08-07T08:00:00Z",
                "match_is_end": "1",
                "home_points": "3",
                "away_points": "2",
                "match_end": "REG",
            },
            {
                "id": "upcoming-1",
                "datetime": "2026-08-08T09:00:00Z",
                "match_is_end": "0",
                "home_points": "",
                "away_points": "",
                "match_end": "",
            },
        ]
    )


def test_loads_nhl_quality_gate_profile() -> None:
    config = load_tournament_quality_gate_config("nhl")

    assert config.tournament == "nhl"
    assert config.schedule_window_hours == 48
    assert config.schedule_finished_values == ("OFF",)
    assert config.schedule_snapshot_filename == "nhl_quality_schedule.csv"
    assert config.schedule_coverage_filename == "nhl_quality_schedule.coverage.json"
    assert config.required_result_fields == ("home_score_ft", "away_score_ft", "match_end")
    assert config.result_field_rules["home_score_ft"].value_type == "integer"
    assert config.result_field_rules["match_end"].allowed_values == ("REG", "OT", "SO")


def test_quality_gate_accepts_complete_schedule_and_completed_results() -> None:
    result = validate_tournament_quality_gate(
        source_rows=_source(),
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert result.is_valid
    assert result.stage == "tournament_quality_gate"
    assert result.tournament == "test_league"
    assert result.errors == []
    assert result.stats == {"schedule_matches": 1, "completed_matches": 1}


def test_quality_gate_rejects_missing_match_from_schedule_window() -> None:
    result = validate_tournament_quality_gate(
        source_rows=_source().query("id != 'upcoming-1'"),
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["В source отсутствуют матчи расписания: 1"]


def test_quality_gate_rejects_duplicate_match_from_schedule_window() -> None:
    source = pd.concat([_source(), _source().query("id == 'upcoming-1'")], ignore_index=True)

    result = validate_tournament_quality_gate(
        source_rows=source,
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["В source дублируются матчи расписания: 1"]


def test_quality_gate_rejects_duplicate_match_in_schedule_snapshot() -> None:
    schedule = pd.concat([_schedule(), _schedule().query("id == 'upcoming-1'")], ignore_index=True)

    result = validate_tournament_quality_gate(
        source_rows=_source(),
        schedule_rows=schedule,
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["Снимок расписания дублирует матчи в окне: 1"]


def test_quality_gate_diagnostic_does_not_include_source_values() -> None:
    source = _source()
    source.loc[source["id"] == "finished-1", "home_points"] = "secret-value"
    source.loc[source["id"] == "finished-1", "away_points"] = ""

    result = validate_tournament_quality_gate(
        source_rows=source,
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert "secret-value" not in " ".join(result.errors)


@pytest.mark.parametrize(
    ("column", "value", "expected_error"),
    [
        ("match_is_end", "0", "У завершённого матча отсутствует финальный статус"),
        ("home_points", "", "У завершённого матча повреждены обязательные поля: home_points"),
    ],
)
def test_quality_gate_rejects_damaged_completed_result(
    column: str, value: str, expected_error: str
) -> None:
    source = _source()
    source.loc[source["id"] == "finished-1", column] = value

    result = validate_tournament_quality_gate(
        source_rows=source,
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == [expected_error]


def test_quality_gate_checks_completed_match_at_watermark_timestamp() -> None:
    source = _source()
    source.loc[source["id"] == "finished-1", "home_points"] = ""

    result = validate_tournament_quality_gate(
        source_rows=source,
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 7, 8, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["У завершённого матча повреждены обязательные поля: home_points"]


@pytest.mark.parametrize("value", ["three", "101"])
def test_quality_gate_rejects_score_outside_configured_type_or_domain(value: str) -> None:
    source = _source()
    source.loc[source["id"] == "finished-1", "home_points"] = value

    result = validate_tournament_quality_gate(
        source_rows=source,
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["У завершённого матча нарушен тип или домен поля: home_points"]


def test_quality_gate_rejects_snapshot_with_insufficient_future_coverage() -> None:
    result = validate_tournament_quality_gate(
        source_rows=_source(),
        schedule_rows=_schedule(),
        config=_config(),
        refreshed_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        last_completed_at=datetime(2026, 8, 6, 12, tzinfo=UTC),
        schedule_covered_until=datetime(2026, 8, 8, 11, tzinfo=UTC),
    )

    assert not result.is_valid
    assert result.errors == ["Снимок расписания не покрывает заданное окно прогноза"]
