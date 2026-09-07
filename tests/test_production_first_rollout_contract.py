"""Контракт production first-rollout, не требующий Docker daemon."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

from scripts.run_production_first_rollout import (
    _assert_logs_are_redacted,
    _clean_worktree_issues,
    _disk_usage,
    _disk_usage_delta,
    _parse_df_disk_usage,
    _parse_memory_usage_bytes,
    _restore_fixture_mount_ownership,
    _restore_runtime_root_ownership,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_commands_use_installed_environment_and_read_only_contract() -> None:
    """Runtime CMD не запускает uv и Compose явно задаёт immutable runtime boundary."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))

    assert 'CMD ["uv", "run"' not in dockerfile
    assert "CMD uv run " not in dockerfile
    services = compose["services"]
    for name in ("api", "telegram-bot", "worker", "archive-sync"):
        service = services[name]
        assert service.get("read_only") is True
        assert service.get("user") == "10001:10001"
    assert services["archive-sync"].get("entrypoint") != [
        "uv",
        "run",
        "python",
        "-m",
        "sports_forecast.deploy.archive_sync_cli",
    ]
    assert "canonical_full_refresh_cli" in dockerfile
    assert '"sports_forecast.bot", "hydra/job_logging=disabled"' in dockerfile
    assert services["source-acquirer"]["command"] == [
        "/app/.venv/bin/python",
        "-m",
        "sports_forecast.orchestration.source_snapshot_cli",
        "--tournament",
        "nhl",
    ]


def test_database_identities_are_file_backed_and_migration_is_explicit() -> None:
    """Compose не раскрывает URLs/passwords и выделяет migration identity."""
    compose_text = (PROJECT_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    services = compose["services"]

    assert "DATABASE_URL: ${" not in compose_text
    assert "SF_MIGRATOR_DATABASE_URL_FILE" in compose_text
    assert "migrator" in services
    assert "role-bootstrap" in services
    assert services["api"]["environment"] == {"DATABASE_URL_FILE": "/run/secrets/api_database_url"}
    assert (
        services["worker"]["environment"]["DATABASE_URL_FILE"] == "/run/secrets/worker_database_url"
    )
    assert services["migrator"]["environment"] == {
        "DATABASE_URL_FILE": "/run/secrets/migrator_database_url"
    }
    assert "sf_api_reader" in (PROJECT_ROOT / "deploy/postgres/init-roles.sh").read_text(
        encoding="utf-8"
    )
    grants = (PROJECT_ROOT / "sports_forecast/deploy/database_roles.py").read_text(encoding="utf-8")
    assert (
        "GRANT SELECT ON TABLE predictions, tournament_publication_states TO sf_api_reader"
        in grants
    )
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO sf_api_reader" not in grants
    assert "ON ALL TABLES IN SCHEMA public TO sf_refresh_writer" not in grants
    assert (
        "ON TABLE predictions, tournament_publication_states, worker_executions, model_deployments, "
        "refresh_locks, canonical_events, canonical_event_revisions, refresh_watermarks, bootstrap_imports"
        in grants
    )
    assert "REVOKE ALL ON TABLE alembic_version FROM sf_api_reader, sf_refresh_writer" in grants
    assert "ON ALL SEQUENCES IN SCHEMA public" not in grants
    assert "ALTER DEFAULT PRIVILEGES" not in grants
    bootstrap = (PROJECT_ROOT / "deploy/postgres/init-roles.sh").read_text(encoding="utf-8")
    assert "--set=api_password=" not in bootstrap
    assert 'psql "$DATABASE_URL"' not in bootstrap
    assert "PGPASSFILE" in bootstrap
    source_environment = services["source-acquirer"]["environment"]
    assert "ODDS_API_KEY_FREE" not in source_environment
    assert source_environment["ODDS_API_KEY_FREE_FILE"] == "/run/secrets/odds_api_key_free"


def test_runtime_grants_cover_actual_api_and_worker_tables() -> None:
    """Whitelist grants соответствуют tables, к которым обращаются runtime commands."""
    grants = (PROJECT_ROOT / "sports_forecast/deploy/database_roles.py").read_text(encoding="utf-8")

    assert "tournament_publication_states TO sf_api_reader" in grants
    for table in (
        "predictions",
        "tournament_publication_states",
        "worker_executions",
        "model_deployments",
        "refresh_locks",
        "canonical_events",
        "canonical_event_revisions",
        "refresh_watermarks",
        "bootstrap_imports",
    ):
        assert table in grants


def test_first_rollout_runner_and_tag_gate_are_checked_in() -> None:
    """Release tag не может перейти к publication без локально воспроизводимого gate."""
    runner = PROJECT_ROOT / "scripts/run_production_first_rollout.py"
    workflow = (PROJECT_ROOT / ".github/workflows/production-first-rollout-contract.yml").read_text(
        encoding="utf-8"
    )

    assert runner.is_file()
    runner_source = runner.read_text(encoding="utf-8")
    assert "--read-only" in runner_source
    assert '"role-bootstrap"' in runner_source
    assert '"pg_dump"' in runner_source
    assert '"api_ready"' in runner_source
    assert '"isolated_restore"' in runner_source
    assert '"services"' in runner_source
    assert '"resources"' in runner_source
    assert '"ports"' in runner_source
    assert '"all_service_logs_redacted"' in runner_source
    assert '"model_pointer"' in runner_source
    assert "has_table_privilege" in runner_source
    assert "rollout_restore_sentinel" in runner_source
    assert "_clean_worktree_issues" in runner_source
    assert '"--untracked-files=all"' in runner_source
    assert "runtime_identity_probes" in runner_source
    assert "run_production_first_rollout.py" in workflow
    assert "workflow_call:" in workflow
    docker_workflow = (PROJECT_ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*.*.*"]' in docker_workflow
    assert "first-rollout:" in docker_workflow
    assert "needs: [verify, build-artifacts, first-rollout]" in docker_workflow
    assert "workflow_dispatch:" not in docker_workflow


def test_first_rollout_tests_prebuilt_image_archives_before_exact_publish() -> None:
    """Rollout и publication используют один Docker archive без повторной сборки."""
    rollout = yaml.safe_load(
        (PROJECT_ROOT / ".github/workflows/production-first-rollout-contract.yml").read_text(
            encoding="utf-8"
        )
    )
    docker = yaml.safe_load(
        (PROJECT_ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8")
    )

    rollout_text = (
        PROJECT_ROOT / ".github/workflows/production-first-rollout-contract.yml"
    ).read_text(encoding="utf-8")
    assert "docker build " not in rollout_text
    assert "actions/download-artifact@" in rollout_text
    assert re.search(r"registry:2@sha256:[0-9a-f]{64}", rollout_text)
    for step in rollout["jobs"]["first-rollout"]["steps"]:
        if "uses" in step:
            assert re.search(r"@[0-9a-f]{40}(?:\s|$)", step["uses"])
    for job in docker["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert re.search(r"@[0-9a-f]{40}(?:\s|$)", step["uses"])

    assert docker["jobs"]["first-rollout"]["needs"] == ["verify", "build-artifacts"]
    artifact_build = docker["jobs"]["build-artifacts"]
    build_step = next(
        step
        for step in artifact_build["steps"]
        if step.get("name") == "Build Docker image archive once"
    )
    assert "type=docker" in build_step["with"]["outputs"]
    assert ".docker.tar" in build_step["with"]["outputs"]
    assert "docker load --input artifacts/release-oci/api.docker.tar" in rollout_text

    publish_steps = docker["jobs"]["build-push"]["steps"]
    assert not any("build-push-action" in step.get("uses", "") for step in publish_steps)
    assert any("TESTED_DIGEST" in step.get("run", "") for step in publish_steps)
    assert any(
        "docker load --input artifacts/release-oci/${{ matrix.target }}.docker.tar"
        in step.get("run", "")
        for step in publish_steps
    )


def test_migration_runbook_uses_file_backed_migration_profile() -> None:
    """Runbook не предлагает устаревший uv run внутри runtime image."""
    runbook = (PROJECT_ROOT / "docs/operations/database-migrations.md").read_text(encoding="utf-8")

    assert "uv run alembic" not in runbook
    assert "role-bootstrap" in runbook
    assert "sf_migrator" in runbook


def test_handoff_describes_compose_secrets_as_file_paths() -> None:
    """Operations получает пути к runtime secret files, а не значения в Compose env."""
    handoff = (PROJECT_ROOT / "docs/operations/production-handoff.md").read_text(encoding="utf-8")

    assert "`*_FILE` paths" in handoff
    assert "`DATABASE_URL` — только host CLI" not in handoff
    systemd_profile = (PROJECT_ROOT / "deploy/systemd/refresh-profile.env.example").read_text(
        encoding="utf-8"
    )
    assert "SF_WORKER_DATABASE_URL_FILE=" in systemd_profile
    assert "SF_API_DATABASE_URL_FILE=" in systemd_profile
    assert "SF_WORKER_DATABASE_URL=" not in systemd_profile
    assert "POSTGRES_PASSWORD=" not in systemd_profile
    assert "SF_POSTGRES_PASSWORD_FILE=" in systemd_profile


def test_clean_worktree_permits_only_downloaded_docker_archives() -> None:
    """Загрузка archive не маскирует tracked files либо другие untracked paths."""
    assert _clean_worktree_issues("?? artifacts/release-oci/api.docker.tar\n") == []
    assert _clean_worktree_issues(" M Dockerfile\n?? artifacts/release-oci/api.docker.tar\n") == [
        " M Dockerfile"
    ]
    assert _clean_worktree_issues("?? artifacts/production-first-rollout.json\n") == [
        "?? artifacts/production-first-rollout.json"
    ]


def test_cleanup_restores_runner_ownership_after_runtime_containers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cleanup временного root не зависит от UID файлов, созданных контейнером."""
    commands: list[list[str]] = []

    def record(command: list[str], **_: object) -> None:
        commands.append(command)

    monkeypatch.setattr("scripts.run_production_first_rollout._run", record)

    _restore_runtime_root_ownership(tmp_path, image="fixture-worker@sha256:test")

    assert commands == [
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--mount",
            f"type=bind,src={tmp_path},dst=/runtime-root",
            "--entrypoint",
            "/bin/chown",
            "fixture-worker@sha256:test",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/runtime-root",
        ]
    ]


def test_cleanup_restores_exact_fixture_mounts_owned_by_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cleanup возвращает ownership только путей, переданных в Compose."""
    commands: list[list[str]] = []
    mounts = {
        "runtime_models": tmp_path / "runtime_models",
        "canonical_source": tmp_path / "source" / "nhl",
        "operational_archive": tmp_path / "archive",
        "archive_sync_state": tmp_path / "sync-state",
    }

    def record(command: list[str], **_: object) -> None:
        commands.append(command)

    monkeypatch.setattr("scripts.run_production_first_rollout._run", record)

    _restore_fixture_mount_ownership(mounts, image="fixture-worker@sha256:test")

    assert commands == [
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--mount",
            f"type=bind,src={mounts['runtime_models']},dst=/cleanup/runtime_models",
            "--mount",
            f"type=bind,src={mounts['canonical_source']},dst=/cleanup/canonical_source",
            "--mount",
            f"type=bind,src={mounts['operational_archive']},dst=/cleanup/operational_archive",
            "--mount",
            f"type=bind,src={mounts['archive_sync_state']},dst=/cleanup/archive_sync_state",
            "--entrypoint",
            "/bin/chown",
            "fixture-worker@sha256:test",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/cleanup",
        ]
    ]


def test_workflow_checks_clean_checkout_before_oci_download() -> None:
    """Downloaded artifact не может скрыть исходную грязь checkout."""
    workflow = (PROJECT_ROOT / ".github/workflows/production-first-rollout-contract.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.index("Verify clean checkout before OCI download") < workflow.index(
        "Download prebuilt OCI images"
    )
    assert 'rm -rf "$fixture_root"' in workflow
    assert 'fixture_root=""' in workflow


def test_log_redaction_gate_rejects_fixture_secret(tmp_path: Path) -> None:
    """Evidence не может стать green при утечке file-backed credential."""
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://secret", encoding="utf-8")

    with pytest.raises(RuntimeError, match="secret"):
        _assert_logs_are_redacted(
            "connected postgresql://secret", {"DATABASE_URL_FILE": str(secret)}
        )


@pytest.mark.parametrize(
    ("docker_stats_value", "expected_bytes"),
    [
        ("512KiB / 1GiB", 512 * 1024),
        ("1.5MiB / 1GiB", 1572864),
        ("2GB / 4GB", 2_000_000_000),
    ],
)
def test_worker_rss_parser_returns_numeric_current_memory(
    docker_stats_value: str, expected_bytes: int
) -> None:
    """Peak RSS evidence использует машиночитаемое значение docker stats."""
    assert _parse_memory_usage_bytes(docker_stats_value) == expected_bytes


@pytest.mark.parametrize("docker_stats_value", ["", "not-a-measurement", "1MiB", "-1MiB / 1GiB"])
def test_worker_rss_parser_rejects_unparseable_measurement(docker_stats_value: str) -> None:
    """Неизмеримый RSS не может дать green first-rollout evidence."""
    with pytest.raises(ValueError, match="RSS"):
        _parse_memory_usage_bytes(docker_stats_value)


def test_disk_evidence_contains_valid_free_space_and_delta(tmp_path: Path) -> None:
    """Evidence содержит проверяемые bytes и не допускает несовпадающие targets."""
    before = {"runtime_models": _disk_usage(tmp_path)}
    after = {"runtime_models": _disk_usage(tmp_path)}

    measurement = before["runtime_models"]
    assert measurement["total_bytes"] > 0
    assert 0 <= measurement["free_bytes"] <= measurement["total_bytes"]
    assert 0 <= measurement["used_bytes"] <= measurement["total_bytes"]
    assert _disk_usage_delta(before, after) == {"runtime_models": 0}

    with pytest.raises(ValueError, match="disk targets"):
        _disk_usage_delta(before, {"database": after["runtime_models"]})


def test_container_df_parser_returns_numeric_disk_measurement() -> None:
    """Docker-owned named volume измеряется внутри container, а не через host stat."""
    assert _parse_df_disk_usage(
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/vda 1000 250 750 25% /data\n"
    ) == {
        "total_bytes": 1000 * 1024,
        "used_bytes": 250 * 1024,
        "free_bytes": 750 * 1024,
    }

    with pytest.raises(ValueError, match="disk"):
        _parse_df_disk_usage("Filesystem 1B-blocks Used Available Use% Mounted on\n")
