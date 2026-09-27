"""Контракт production first-rollout, не требующий Docker daemon."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.build_production_compose_env_fixture import build_fixture
from scripts.run_production_first_rollout import (
    _assert_logs_are_redacted,
    _clean_worktree_issues,
    _disk_usage,
    _disk_usage_delta,
    _parse_df_disk_usage,
    _parse_memory_usage_bytes,
    _probe_runtime_identities,
    _restore_fixture_mount_ownership,
    _restore_runtime_root_ownership,
    _smoke_calendar_endpoints,
    _start_s3_fixture,
    _sync_operational_archives,
)
from scripts.verify_production_compose_contract import verify_contract


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_fixture_supplies_control_and_notification_requirements(
    tmp_path: Path,
) -> None:
    """First-rollout fixture создаёт только фиктивные secret files и admin mapping."""
    env_file = tmp_path / "production.env"
    build_fixture(env_file, root=tmp_path, app_version="1.2.0")
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )

    required_values = {
        "SF_CONTROL_API_DB_PASSWORD_FILE",
        "SF_CONTROL_DATABASE_URL_FILE",
        "SF_CONTROL_API_KEY_FILE",
        "SF_DATA_CYCLE_NOTIFICATION_ALIASES",
        "BOT_ADMIN_USER_IDS",
        "BOT_NOTIFICATION_DESTINATIONS_FILE",
    }
    assert required_values <= values.keys()
    assert values["SF_DATA_CYCLE_NOTIFICATION_ALIASES"] == "nhl_admins"
    assert values["BOT_ADMIN_USER_IDS"] == "1"
    for key in required_values - {
        "SF_DATA_CYCLE_NOTIFICATION_ALIASES",
        "BOT_ADMIN_USER_IDS",
    }:
        assert Path(values[key]).is_file()
    assert Path(values["SF_CONTROL_API_DB_PASSWORD_FILE"]).read_text(encoding="utf-8") == (
        "fixture-control-api-password"
    )
    assert Path(values["SF_CONTROL_DATABASE_URL_FILE"]).read_text(encoding="utf-8") == (
        "postgresql://sf_control_api:fixture-control-api-password@db:5432/sports_forecast"
    )
    assert Path(values["SF_CONTROL_API_KEY_FILE"]).read_text(encoding="utf-8") == (
        "fixture-control-api-key"
    )
    assert Path(values["BOT_NOTIFICATION_DESTINATIONS_FILE"]).read_text(encoding="utf-8") == (
        '{"nhl_admins":-1001234567890}'
    )


def test_production_compose_fixture_renders_all_first_rollout_profiles(tmp_path: Path) -> None:
    """Fixture закрывает Compose interpolation для migration и runtime profiles."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose недоступен для rendered production config")
    env_file = tmp_path / "production.env"
    build_fixture(env_file, root=tmp_path, app_version="1.2.0")
    result = subprocess.run(
        [
            docker,
            "compose",
            "--project-name",
            "sf-first-rollout-fixture",
            "--env-file",
            str(env_file),
            "-f",
            str(PROJECT_ROOT / "docker-compose.prod.yml"),
            "--profile",
            "migration",
            "--profile",
            "worker",
            "--profile",
            "operational-sync",
            "--profile",
            "source-acquisition",
            "--profile",
            "scheduler",
            "config",
        ],
        cwd=PROJECT_ROOT,
        env={"PATH": str(Path(docker).parent), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = tmp_path / "rendered.yml"
    rendered.write_text(result.stdout, encoding="utf-8")
    verify_contract(rendered, model_runtime_root=tmp_path / "runtime_models")

    config = yaml.safe_load(result.stdout)
    config["services"]["api"]["environment"]["SF_CONTROL_DATABASE_URL_FILE"] = (
        "postgresql://unsafe@db/sports_forecast"
    )
    rendered.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="reader/control credentials"):
        verify_contract(rendered, model_runtime_root=tmp_path / "runtime_models")

    config = yaml.safe_load(result.stdout)
    config["services"]["data-cycle-dispatcher"]["mem_limit"] = "512m"
    rendered.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="не оставляет минимум"):
        verify_contract(rendered, model_runtime_root=tmp_path / "runtime_models")


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
    assert dockerfile.count('"hydra/job_logging=stdout"') == 2
    assert dockerfile.count('"hydra.output_subdir=null"') == 2
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
    assert services["api"]["environment"]["DATABASE_URL_FILE"] == "/run/secrets/api_database_url"
    assert services["api"]["environment"]["SF_CONTROL_DATABASE_URL_FILE"] == (
        "/run/secrets/control_database_url"
    )
    assert services["api"]["environment"]["SF_CONTROL_API_KEY_FILE"] == (
        "/run/secrets/control_api_key"
    )
    assert services["api"]["environment"]["SF_DATA_CYCLE_NOTIFICATION_ALIASES"] == (
        "${SF_DATA_CYCLE_NOTIFICATION_ALIASES:?set safe notification aliases}"
    )
    assert services["worker"]["environment"]["SF_DATA_CYCLE_NOTIFICATION_ALIASES"] == (
        "${SF_DATA_CYCLE_NOTIFICATION_ALIASES:?set safe notification aliases}"
    )
    bot = services["telegram-bot"]
    assert bot["environment"]["BOT_NOTIFICATION_DESTINATIONS_FILE"] == (
        "/run/secrets/bot_notification_destinations"
    )
    assert "bot_notification_destinations" in bot["secrets"]
    assert "BOT_NOTIFICATION_DESTINATIONS_FILE" not in services["api"]["environment"]
    assert compose["secrets"]["bot_notification_destinations"]["file"] == (
        "${BOT_NOTIFICATION_DESTINATIONS_FILE:?set BOT_NOTIFICATION_DESTINATIONS_FILE}"
    )
    assert "-1001234567890" not in compose_text
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
    assert "GRANT SELECT ON TABLE predictions, tournament_publication_states," in grants
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO sf_api_reader" not in grants
    assert "ON ALL TABLES IN SCHEMA public TO sf_refresh_writer" not in grants
    worker_grant = next(
        statement
        for statement in grants.splitlines()
        if "sf_refresh_writer" in statement and "GRANT SELECT, INSERT, UPDATE, DELETE" in statement
    )
    for table in (
        "predictions",
        "tournament_publication_states",
        "worker_executions",
        "model_deployments",
        "refresh_locks",
        "canonical_events",
        "canonical_event_revisions",
        "calendar_coverages",
        "refresh_watermarks",
        "bootstrap_imports",
    ):
        assert table in worker_grant
    assert (
        "REVOKE ALL ON TABLE alembic_version FROM sf_api_reader, sf_control_api, sf_refresh_writer"
        in grants
    )
    assert "GRANT SELECT ON TABLE data_cycle_notification_outbox TO sf_control_api" in grants
    assert (
        "GRANT UPDATE (status, attempts, available_at, lease_token, lease_until, last_error_code, delivered_at)"
        " ON TABLE data_cycle_notification_outbox TO sf_control_api"
    ) in grants
    assert (
        "GRANT USAGE, SELECT ON SEQUENCE data_cycle_notification_outbox_id_seq TO sf_control_api"
        not in grants
    )
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

    reader_grant = next(
        statement
        for statement in grants.splitlines()
        if statement.startswith('    "GRANT SELECT ON TABLE') and "sf_api_reader" in statement
    )
    assert "tournament_publication_states" in reader_grant
    control_outbox_update = next(
        statement
        for statement in grants.splitlines()
        if "UPDATE (status, attempts" in statement and "data_cycle_notification_outbox" in statement
    )
    assert "data_cycle_runs" not in control_outbox_update
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
    assert (
        "has_table_privilege('sf_api_reader', 'public.data_cycle_stage_results', 'SELECT')"
        in runner_source
    )
    assert (
        "has_column_privilege('sf_api_reader', 'public.data_cycle_runs', 'run_id', 'SELECT')"
        in runner_source
    )
    assert (
        "has_column_privilege('sf_api_reader', 'public.data_cycle_runs', 'tournament', 'SELECT')"
        in runner_source
    )
    assert "JOIN data_cycle_runs" in runner_source
    assert "_sync_operational_archives(compose, values=values)" in runner_source
    assert "sports_forecast.deploy.archive_sync_cli" in runner_source
    assert 'if role_contract != "t|t|t|t|f|f":' in runner_source
    assert runner_source.index('evidence["health"]["api_ready"] = "ok"') < runner_source.index(
        "_smoke_calendar_endpoints(compose)"
    )
    assert runner_source.index("_smoke_calendar_endpoints(compose)") < runner_source.index(
        'up", "-d", "telegram-bot'
    )
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


def test_first_rollout_api_reader_probe_executes_calendar_stage_join(monkeypatch) -> None:
    """First-rollout role probe runs the exact join used by calendar readiness."""
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run_one_shot_checked",
        lambda command, **_kwargs: commands.append(command),
    )

    _probe_runtime_identities(
        project_name="fixture",
        values={
            "SF_API_DATABASE_URL_FILE": "/tmp/api-url",
            "SF_WORKER_DATABASE_URL_FILE": "/tmp/worker-url",
        },
        postgres_image="postgres:fixture",
    )

    api_probe_command = commands[0][-1]
    assert "JOIN data_cycle_runs AS run ON run.run_id = stage.run_id" in api_probe_command
    assert "WHERE run.tournament = 'nhl' AND stage.stage = 'data_odds'" in api_probe_command
    syntax = subprocess.run(
        ["sh", "-n", "-c", api_probe_command], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr


def test_first_rollout_smokes_calendar_periods_without_logging_payloads(monkeypatch) -> None:
    """Local release rehearsal checks NHL calendar 0/7/30 through API container."""
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run",
        lambda command, **_kwargs: commands.append(command),
    )

    _smoke_calendar_endpoints(["docker", "compose", "-f", "docker-compose.prod.yml"])

    assert [command[-1] for command in commands] == [
        "http://localhost:8000/calendar/nhl?period=today",
        "http://localhost:8000/calendar/nhl?period=7",
        "http://localhost:8000/calendar/nhl?period=30",
    ]
    for command in commands:
        assert command[-5:-1] == ["curl", "-fsS", "-o", "/dev/null"]
        assert command[:3] == ["docker", "compose", "-f"]


def test_first_rollout_syncs_each_artifact_with_runner_cli_and_matching_prefix(
    tmp_path: Path, monkeypatch
) -> None:
    """S3 fixture uses the production CLI, artifact path and per-artifact prefix contract."""
    archive_root = tmp_path / "archive"
    canonical_artifact = archive_root / "operational-archive" / f"sha256:{'a' * 64}"
    source_state_artifact = (
        archive_root / "operational-archive" / "nhl-source-state" / "v1" / f"sha256:{'b' * 64}"
    )
    canonical_artifact.mkdir(parents=True)
    source_state_artifact.mkdir(parents=True)
    manifests = [canonical_artifact / "manifest.json", source_state_artifact / "manifest.json"]
    for manifest in manifests:
        manifest.write_text("{}", encoding="utf-8")

    captured: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="\0".join(map(str, manifests)) + "\0", stderr=""
        ),
    )
    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run_one_shot_checked",
        lambda command, **_kwargs: captured.append(command),
    )

    count = _sync_operational_archives(
        ["docker", "compose", "--project-name", "fixture"],
        values={
            "SF_OPERATIONAL_ARCHIVE_ROOT": str(archive_root),
            "SF_OPERATIONAL_ARCHIVE_PREFIX": "fixture-operational",
            "SF_NHL_SOURCE_STATE_PREFIX": "fixture-source-state",
        },
    )

    assert count == 2
    assert len(captured) == 2
    for command in captured:
        assert command[command.index("archive-sync") + 1 : command.index("archive-sync") + 5] == [
            "/app/.venv/bin/python",
            "-m",
            "sports_forecast.deploy.archive_sync_cli",
            "sync",
        ]
        assert "--archive" in command
        assert "--state-root" in command
        assert command[command.index("--state-root") + 1] == "/app/sync-state"
    assert captured[0][captured[0].index("--prefix") + 1] == "fixture-operational"
    assert captured[1][captured[1].index("--prefix") + 1] == "fixture-source-state"


@pytest.mark.parametrize(
    ("present_type", "missing_type"),
    (("canonical", "source-state"), ("source-state", "canonical")),
)
def test_first_rollout_requires_both_canonical_and_source_state_archives(
    tmp_path: Path, monkeypatch, present_type: str, missing_type: str
) -> None:
    """Успешный rollout требует canonical и NHL source-state artifacts."""
    archive_root = tmp_path / "archive"
    if present_type == "canonical":
        artifact = archive_root / "operational-archive" / f"sha256:{'a' * 64}"
    else:
        artifact = (
            archive_root / "operational-archive" / "nhl-source-state" / "v1" / f"sha256:{'b' * 64}"
        )
    artifact.mkdir(parents=True)
    manifest = artifact / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout=f"{manifest}\0", stderr=""
        ),
    )
    monkeypatch.setattr(
        "scripts.run_production_first_rollout._run_one_shot_checked",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match=f"{missing_type}"):
        _sync_operational_archives(
            ["docker", "compose", "--project-name", "fixture"],
            values={"SF_OPERATIONAL_ARCHIVE_ROOT": str(archive_root)},
        )


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


def test_s3_fixture_uses_project_image_on_compose_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 fixture запускается из переданного immutable project artifact."""
    commands: list[list[str]] = []

    def record(command: list[str], **_: object) -> None:
        commands.append(command)

    monkeypatch.setattr("scripts.run_production_first_rollout._run_one_shot_checked", record)

    _start_s3_fixture(
        fixture_name="sf-rollout-test-s3-fixture",
        network="sf-rollout-test_default",
        image="localhost:5000/sf-rollout-s3-fixture@sha256:" + "0" * 64,
        values={"DATABASE_URL_FILE": "/non-secret-path"},
    )

    assert commands[0][:9] == [
        "docker",
        "run",
        "-d",
        "--name",
        "sf-rollout-test-s3-fixture",
        "--network",
        "sf-rollout-test_default",
        "--network-alias",
        "minio",
    ]
    assert "--read-only" in commands[0]
    assert "--tmpfs" in commands[0]
    assert commands[0][-1] == "localhost:5000/sf-rollout-s3-fixture@sha256:" + "0" * 64


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
