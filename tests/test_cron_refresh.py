"""Tests for cron_refresh CLI (dry-run, command shape)."""

from __future__ import annotations

import pytest

from sports_forecast.orchestration.cron_refresh import main


def test_cron_refresh_dry_run_contains_flock_and_nhl(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "--project-dir",
            str(tmp_path),
            "--tournaments",
            "nhl",
            "--dry-run",
        ],
    )
    assert code == 0
    captured = capsys.readouterr().out
    assert "flock" in captured
    assert "nhl" in captured
    assert "source_refresh" in captured


def test_cron_refresh_dry_run_uses_custom_lock(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = tmp_path / "custom.lock"
    main(
        [
            "--project-dir",
            str(tmp_path),
            "--tournaments",
            "nhl",
            "--lock-file",
            str(lock),
            "--dry-run",
        ],
    )
    captured = capsys.readouterr().out
    assert str(lock) in captured
