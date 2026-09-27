"""Contract for the durable cycle wrapper around the production NHL runner."""

from pathlib import Path

from sports_forecast.orchestration import data_cycle_cli


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runner_executes_reserved_cycle_and_uses_measured_terminal_summary() -> None:
    """Dispatcher run id precedes acquisition and finish status comes from stage results."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")

    assert "data_cycle_cli" in runner
    assert 'pipeline_id="${1:' in runner
    assert 'run_id="${2:' in runner
    assert 'SF_WORKER_RUN_ID="${run_id}"' in runner
    assert 'SF_DATA_CYCLE_RUN_ID="${run_id}"' in runner
    assert 'SF_DATA_CYCLE_OWNER_ID="${owner_id,,}"' in runner
    assert "control create" not in runner
    assert runner.index("control claim") < runner.index("control start-stage")
    assert runner.index("control start-stage") < runner.index("source_snapshot_cli")
    assert "--calendar-attempt" in runner
    assert 'finish-run --run-id "${SF_WORKER_RUN_ID}" --status auto' in runner


def test_lifecycle_cli_accepts_automatic_terminal_status(monkeypatch) -> None:
    """Bounded wrapper can request status derived from persisted stage results."""
    calls: list[tuple[str, str, dict[str, int] | None]] = []

    def finish(run_id: str, *, status: str, summary: dict[str, int] | None = None) -> None:
        calls.append((run_id, status, summary))

    monkeypatch.setattr(data_cycle_cli, "finish_run", finish)

    assert data_cycle_cli.main(["finish-run", "--run-id", "run-1", "--status", "auto"]) == 0
    assert calls == [("run-1", "auto", {})]


def test_lifecycle_cli_heartbeat_uses_claimed_generation(monkeypatch) -> None:
    """Heartbeat CLI forwards the claimed fencing token to the DB service."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", "7")
    monkeypatch.setattr(
        data_cycle_cli,
        "heartbeat_executor",
        lambda run_id, *, owner_generation, at=None: calls.append((run_id, owner_generation)),
    )

    assert data_cycle_cli.main(["heartbeat", "--run-id", "run-long"]) == 0
    assert calls == [("run-long", 7)]


def test_canonical_full_refresh_disables_hydra_filesystem_logging() -> None:
    """Явная Compose-команда сохраняет read-only overrides из Docker CMD."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")
    command = runner.split("canonical_full_refresh_cli \\", 1)[1].split(
        'active_stage="pipeline"', 1
    )[0]

    assert '"hydra/job_logging=disabled"' in command
    assert '"hydra.output_subdir=null"' in command
