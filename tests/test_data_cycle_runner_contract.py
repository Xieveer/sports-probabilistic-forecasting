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
    assert "control create" not in runner
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
