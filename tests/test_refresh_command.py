"""Tests for tournament refresh orchestration command builder."""

from __future__ import annotations

from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


def test_refresh_command_contains_required_stage_sequence() -> None:
    """Command includes source->ingest->clean->features->materialize chain."""
    command = build_refresh_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        features_config="{{ params.features }}",
        market="{{ params.market }}",
        market_spec="{{ params.market_spec }}",
        source_cmd='test -f "data/source/{tournament}/source.csv"',
        lock_file="/tmp/sf_refresh_pipeline.lock",
        lock_wait_seconds=120,
    )

    assert "flock -w 120" in command
    assert "for tournament in" in command
    assert 'test -f "data/source/"$tournament"/source.csv"' in command
    assert "$1/source.csv" not in command
    assert "sports_forecast.data.ingest" in command
    assert "sports_forecast.data.clean" in command
    assert "sports_forecast.features.features_build" in command
    assert "sports_forecast.materialize" in command
    assert "algorithm=catboost" in command
    assert "features={{ params.features }}" in command


def test_refresh_command_sets_tournament_filter_for_ingest_and_clean() -> None:
    """Ingest and clean are scoped by SF_TOURNAMENT_FILTER."""
    command = build_refresh_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        features_config="basic",
        market="winner",
        market_spec="winner",
        source_cmd='echo "source"',
        lock_file="/tmp/sf_refresh_pipeline.lock",
        lock_wait_seconds=120,
    )

    assert (
        'SF_TOURNAMENT_FILTER="$tournament" uv run python -m sports_forecast.data.ingest' in command
    )
    assert (
        'SF_TOURNAMENT_FILTER="$tournament" uv run python -m sports_forecast.data.clean' in command
    )
    assert '[ "$valid_count" -gt 0 ]' in command
    assert "materialize tournament=" in command
    assert "algorithm=catboost" in command
    assert "features=basic" in command


def test_refresh_command_accepts_custom_algorithm_for_materialize() -> None:
    """Materialize stage receives algorithm_config for Hydra."""
    command = build_refresh_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="nhl",
        features_config="advanced",
        market="winner_withOT",
        market_spec="winner_withOT",
        source_cmd='echo "source"',
        lock_file="/tmp/sf_refresh_pipeline.lock",
        lock_wait_seconds=120,
        algorithm_config="catboost_reg",
    )

    assert "algorithm=catboost_reg" in command
    assert "features=advanced" in command


def test_refresh_command_supports_legacy_positional_source_contract() -> None:
    """Legacy source command still gets tournament as positional argument."""
    command = build_refresh_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        features_config="basic",
        market="winner",
        market_spec="winner",
        source_cmd='test -f "data/source/$1/source.csv"',
        lock_file="/tmp/sf_refresh_pipeline.lock",
        lock_wait_seconds=120,
    )

    assert 'test -f "data/source/$1/source.csv" "$tournament"' in command
