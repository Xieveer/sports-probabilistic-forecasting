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


@pytest.mark.parametrize(
    ("failure_code", "stage"),
    [
        ("canonical_freshness_failed", "quality"),
        ("materialization_failed", "publication"),
        ("bundle_verification_failed", "predictions"),
    ],
)
def test_failed_refresh_logs_run_stage_and_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    failure_code: str,
    stage: str,
) -> None:
    """Оператор связывает ошибку публикации с записью Data Cycle."""
    monkeypatch.setenv("SF_WORKER_RUN_ID", "daily-42")
    monkeypatch.setenv("SF_MODEL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("SF_APP_VERSION", "1.3.1")
    monkeypatch.setenv("SF_OPERATIONAL_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setattr(
        cli,
        "run_full_refresh",
        lambda *_args, **_kwargs: FullRefreshResult(published=False, failure_code=failure_code),
    )
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)

    with caplog.at_level("ERROR"), pytest.raises(SystemExit) as exit_info:
        cli.main.__wrapped__(OmegaConf.create({"logging": {"level": "INFO"}}))

    assert exit_info.value.code == 1
    assert "run_id='daily-42'" in caplog.text
    assert f"stage={stage}" in caplog.text
    assert failure_code in caplog.text
