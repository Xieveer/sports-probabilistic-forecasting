"""Contract for the durable cycle wrapper around the production NHL runner."""

import json
import os
import shlex
import subprocess
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
    source_command = runner.split("source_snapshot_cli \\", 1)[1].split("# WorkerExecution", 1)[0]
    assert "--odds-enabled false" in source_command
    assert '--odds-enabled "${data_odds_enabled}"' not in source_command
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


def test_canonical_full_refresh_uses_stdout_hydra_logging_without_output_dir() -> None:
    """Явная команда сохраняет stdout logging и read-only overrides из Docker CMD."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")
    command = runner.split("canonical_full_refresh_cli \\", 1)[1].split(
        'active_stage="pipeline"', 1
    )[0]

    assert '"hydra/job_logging=stdout"' in command
    assert '"hydra.output_subdir=null"' in command


def test_archive_sync_runner_executes_the_installed_application_cli() -> None:
    """Compose CMD override must name archive_sync_cli, not shell's system sync."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")
    archive_command = runner.rsplit("archive-sync \\", maxsplit=1)[1]
    archive_command = archive_command.split("control finish-stage", 1)[0]

    assert "/app/.venv/bin/python -m sports_forecast.deploy.archive_sync_cli" in archive_command
    assert 'sync --archive "${container_artifact}"' in archive_command
    assert '--state-root /app/sync-state --prefix "${prefix}"' in archive_command
    assert "archive-sync \\\n    sync --archive" not in archive_command


def test_archive_manifest_loop_keeps_compose_from_consuming_the_manifest_stream(
    tmp_path: Path,
) -> None:
    """The actual loop syncs each manifest when Compose consumes all stdin."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")
    archive_loop = runner.split("while IFS= read -r -d '' manifest; do", 1)[1].split(
        'done <"${manifest_list}"', 1
    )[0]
    archive_loop = (
        "while IFS= read -r -d '' manifest; do" + archive_loop + 'done <"${manifest_list}"'
    )
    command_start = archive_loop.index("  run_with_heartbeat /usr/bin/docker compose")
    command_end = archive_loop.index(
        "\n", archive_loop.index('--prefix "${prefix}"', command_start)
    )
    compose_command = archive_loop[command_start:command_end]
    stdin_redirect = " </dev/null" if "</dev/null" in compose_command else ""
    archive_loop = (
        archive_loop[:command_start]
        + '  run_with_heartbeat fake_compose "${container_artifact}"'
        + stdin_redirect
        + archive_loop[command_end:]
    )

    archive_root = tmp_path / "archive-root"
    manifest_list = tmp_path / "manifests.list"
    sync_log = tmp_path / "archive-sync.log"
    manifests = [
        archive_root / "operational-archive" / name / "manifest.json"
        for name in ("canonical", "source-state", "additional")
    ]
    for manifest in manifests:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
    manifest_list.write_bytes(b"".join(os.fsencode(path) + b"\0" for path in manifests))
    script = "\n".join(
        [
            f"SF_OPERATIONAL_ARCHIVE_ROOT={shlex.quote(str(archive_root))}",
            'SF_OPERATIONAL_ARCHIVE_PREFIX="operational-archive"',
            f"manifest_list={shlex.quote(str(manifest_list))}",
            "artifact_count=0",
            'run_with_heartbeat() { "$@"; }',
            f"SYNC_LOG={shlex.quote(str(sync_log))}",
            'fake_compose() { printf "%s\\n" "$1" >>"$SYNC_LOG"; cat >/dev/null; }',
            archive_loop,
            'printf "count=%s\\n" "$artifact_count"',
        ]
    )
    completed = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env=os.environ.copy(),
    )

    assert 'done <"${manifest_list}"' in runner
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "count=3"
    assert sync_log.read_text(encoding="utf-8").splitlines() == [
        f"/app/archive/operational-archive/{name}"
        for name in ("canonical", "source-state", "additional")
    ]


def test_runner_requires_both_current_run_archives_before_model_work() -> None:
    """Только два archive ID из descriptor текущего run допускают Worker."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")

    assert "list-run-archive-manifests.py \\" in runner
    assert '"${SF_OPERATIONAL_ARCHIVE_ROOT}" "${SF_WORKER_RUN_ID}"' in runner
    assert runner.index("if (( artifact_count != 2 )); then") < runner.index(
        "--status success --counts"
    )
    assert runner.index("if (( artifact_count != 2 )); then") < runner.index(
        "canonical_full_refresh_cli"
    )


def test_run_archive_list_is_bound_to_descriptor_and_rejects_missing_artifact(
    tmp_path: Path,
) -> None:
    """Старые manifest не подменяют текущий canonical/source snapshot."""
    helper = PROJECT_ROOT / "deploy/systemd/list-run-archive-manifests.py"
    run_id = "00000000-0000-4000-8000-000000000034"
    canonical_id = "sha256:" + "a" * 64
    source_id = "sha256:" + "b" * 64
    descriptor = tmp_path / "run-inputs" / f"{run_id}.json"
    descriptor.parent.mkdir()
    descriptor.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "canonical_artifact_id": canonical_id,
                "source_artifact_id": source_id,
            }
        ),
        encoding="utf-8",
    )
    canonical = tmp_path / "operational-archive" / canonical_id / "manifest.json"
    source = tmp_path / "operational-archive/nhl-source-state/v1" / source_id / "manifest.json"
    for manifest in (canonical, source):
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}", encoding="utf-8")
    command = ["python3", str(helper), str(tmp_path), run_id]
    listed = subprocess.run(command, capture_output=True, check=False)
    assert listed.returncode == 0
    assert listed.stdout == (str(canonical) + "\0" + str(source) + "\0").encode()

    source.unlink()
    missing = subprocess.run(command, capture_output=True, check=False)
    assert missing.returncode != 0
    assert missing.stdout == b""


def test_runner_syncs_pinned_input_before_features_without_daily_odds() -> None:
    """Стадия Object Storage предшествует Worker inference без future odds."""
    runner = (PROJECT_ROOT / "deploy/systemd/run-canonical-refresh.sh").read_text(encoding="utf-8")

    assert runner.index("source_snapshot_cli") < runner.index("canonical_run_input_cli")
    assert runner.index("canonical_run_input_cli") < runner.index("archive_sync_cli")
    assert runner.index("archive_sync_cli") < runner.index("canonical_full_refresh_cli")
    assert "--odds-enabled false" in runner
    assert "SF_DATA_ODDS_ENABLED" not in runner
    assert '"data_odds_enabled=' not in runner
