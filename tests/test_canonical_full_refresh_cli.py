"""CLI contract bounded canonical full-refresh."""

from __future__ import annotations

from pathlib import Path

import pytest
from omegaconf import OmegaConf

from sports_forecast.orchestration import canonical_full_refresh_cli as cli
from sports_forecast.orchestration.canonical_full_refresh import FullRefreshResult


def test_cli_passes_scheduler_inputs_to_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI передаёт проверенный archive root Worker без provider reimport."""
    monkeypatch.setenv("SF_WORKER_RUN_ID", "daily-1")
    monkeypatch.setenv("SF_MODEL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("SF_APP_VERSION", "1.1.0")
    monkeypatch.setenv("SF_OPERATIONAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    captured: dict[str, object] = {}

    def run(cfg: object, **kwargs: object) -> FullRefreshResult:
        captured.update(kwargs)
        return FullRefreshResult(published=True)

    monkeypatch.setattr(cli, "run_full_refresh", run)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    cli.main.__wrapped__(OmegaConf.create({"logging": {"level": "INFO"}}))
    assert captured["run_id"] == "daily-1"
    assert captured["prepared_archive_root"] == tmp_path / "archive"
    assert "source_csv" not in captured


def test_cli_treats_repeated_finished_run_as_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Повтор scheduler run_id не является ошибкой публикации."""
    monkeypatch.setenv("SF_WORKER_RUN_ID", "daily-1")
    monkeypatch.setenv("SF_MODEL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("SF_APP_VERSION", "1.1.0")
    monkeypatch.setenv("SF_OPERATIONAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setattr(
        cli,
        "run_full_refresh",
        lambda *_args, **_kwargs: FullRefreshResult(published=False, already_finished=True),
    )
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)

    cli.main.__wrapped__(OmegaConf.create({"logging": {"level": "INFO"}}))
