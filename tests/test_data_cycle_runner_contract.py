"""Contract for the durable cycle wrapper around the production NHL runner."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runner_reserves_cycle_before_acquisition_and_captures_failure() -> None:
    """Source acquisition failures happen after durable run creation and are terminalized."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")

    assert "data_cycle_cli" in runner
    assert runner.index("control create") < runner.index("source_snapshot_cli")
    assert "--calendar-attempt" in runner
    assert "finish-run" in runner
