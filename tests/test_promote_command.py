"""Tests for per-tournament promote command builder."""

from __future__ import annotations

from sports_forecast.deploy.promote_command import (
    build_promote_per_tournament_command,
)


def test_build_promote_command_contains_per_tournament_loop() -> None:
    """Command uses shell loop and per-tournament experiment name."""
    command = build_promote_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        market_spec_expr="{{ params.market_spec }}",
        metric="test_logloss",
        direction="minimize",
        top_n=5,
    )

    assert "IFS=',' read -r -a tournaments" in command
    assert 'for tournament in "${tournaments[@]}"; do ' in command
    assert '--experiment "${tournament}__{{ params.market_spec }}"' in command
    assert "--metric test_logloss " in command
    assert "--direction minimize " in command
    assert "--top-n 5 || exit 1; " in command


def test_build_promote_command_has_non_empty_guard() -> None:
    """Command fails when no valid tournaments were parsed."""
    command = build_promote_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        market_spec_expr="{{ params.market_spec }}",
        metric="test_auc",
        direction="maximize",
        top_n=3,
    )

    assert "valid_count=0" in command
    assert "valid_count=$((valid_count + 1)); " in command
    assert '[ "$valid_count" -gt 0 ]' in command


def test_build_promote_command_has_fail_fast_guards() -> None:
    """Command enforces fail-fast for promoter failures."""
    command = build_promote_per_tournament_command(
        project_dir="/app",
        uv_run="uv run",
        tournaments_expr="{{ params.tournaments }}",
        market_spec_expr="{{ params.market_spec }}",
        metric="test_auc",
        direction="maximize",
        top_n=3,
    )

    assert "set -e && " in command
    assert "|| exit 1; " in command
