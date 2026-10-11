"""Диагностика ошибок lifecycle CLI без раскрытия exception details."""

from __future__ import annotations

import pytest

from sports_forecast.orchestration import data_cycle_cli


RUN_ID = "00000000-0000-4000-8000-000000000042"


def test_failed_stage_action_logs_run_and_stage_without_exception_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ошибку этапа можно связать с запуском, не печатая внешние детали."""

    def fail(_run_id: str, _stage: str) -> None:
        raise ValueError("private provider payload")

    monkeypatch.setattr(data_cycle_cli, "start_stage", fail)
    with caplog.at_level("ERROR"):
        result = data_cycle_cli.main(["start-stage", "--run-id", RUN_ID, "--stage", "quality"])

    assert result == 1
    assert f"run_id='{RUN_ID}'" in caplog.text
    assert "stage='quality'" in caplog.text
    assert "private provider payload" not in caplog.text


def test_failed_terminal_action_logs_safe_failure_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Переданный allow-listed код остаётся доступен при сбое записи итога."""

    def fail(_run_id: str, *, failure_code: str, tournament: str | None) -> None:
        raise ValueError("private database detail")

    monkeypatch.setattr(data_cycle_cli, "fail_run", fail)
    with caplog.at_level("ERROR"):
        result = data_cycle_cli.main(["fail", "--run-id", RUN_ID, "--code", "publication_failed"])

    assert result == 1
    assert "code='publication_failed'" in caplog.text
    assert "private database detail" not in caplog.text


def test_rejected_failure_code_is_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Непроверенный аргумент CLI не должен попасть в собираемые логи."""

    def reject(_run_id: str, *, failure_code: str, tournament: str | None) -> None:
        raise ValueError("Invalid failure_code")

    monkeypatch.setattr(data_cycle_cli, "fail_run", reject)
    with caplog.at_level("ERROR"):
        result = data_cycle_cli.main(["fail", "--run-id", RUN_ID, "--code", "secret=private-value"])

    assert result == 1
    assert "secret=private-value" not in caplog.text
    assert "code='unknown'" in caplog.text


def test_rejected_run_and_stage_are_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Непроверенные идентификатор и этап не раскрываются при отказе репозитория."""

    def reject(_run_id: str, _stage: str) -> None:
        raise ValueError("Invalid run and stage")

    monkeypatch.setattr(data_cycle_cli, "start_stage", reject)
    with caplog.at_level("ERROR"):
        result = data_cycle_cli.main(
            ["start-stage", "--run-id", "secret=run-value", "--stage", "secret=stage-value"]
        )

    assert result == 1
    assert "secret=run-value" not in caplog.text
    assert "secret=stage-value" not in caplog.text
    assert "run_id='unknown'" in caplog.text
    assert "stage='unknown'" in caplog.text
