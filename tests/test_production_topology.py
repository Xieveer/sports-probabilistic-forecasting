"""Контракт минимального production Compose и ручного deployment."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
import tomllib
from pathlib import Path
from typing import cast

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SERVICES = {
    "api",
    "data-cycle-dispatcher",
    "db",
    "telegram-bot",
    "source-acquirer",
    "worker",
    "archive-sync",
    "migrator",
    "role-bootstrap",
}
SYSTEMD_DIR = PROJECT_ROOT / "deploy" / "systemd"


def _load_yaml(relative_path: str) -> dict[str, object]:
    """Загрузить YAML из корня репозитория."""
    content = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    loaded = yaml.safe_load(content)
    assert isinstance(loaded, dict)
    return loaded


def test_production_compose_contains_only_serving_services() -> None:
    """Production Compose не включает training и локальный monitoring."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = compose["services"]

    assert isinstance(services, dict)
    assert set(services) == PRODUCTION_SERVICES
    assert "ports" not in services["api"]
    assert "ports" not in services["db"]
    assert "caddy" not in services
    assert "SF_API_DOMAIN" not in (PROJECT_ROOT / "docker-compose.prod.yml").read_text(
        encoding="utf-8"
    )


def test_scheduler_compose_config_is_independent_of_systemd_environment() -> None:
    """Профиль NHL полностью задаёт Compose interpolation даже в env -i."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose не установлен")
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(SYSTEMD_DIR / "refresh-profile.env.example"),
            "-f",
            str(PROJECT_ROOT / "docker-compose.prod.yml"),
            "--profile",
            "scheduler",
            "config",
            "--quiet",
        ],
        cwd=PROJECT_ROOT,
        env={"PATH": str(Path(docker).parent), "HOME": "/tmp"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    bridge = (SYSTEMD_DIR / "dispatch-data-cycle.sh").read_text(encoding="utf-8")
    assert "SF_COMPOSE_ENV_FILE:-/etc/sports-forecast/refresh/nhl.env" in bridge


def test_production_runtime_images_are_external_and_immutable_inputs() -> None:
    """API, Worker и bot получают image reference извне и не собираются на VPS."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = compose["services"]
    assert isinstance(services, dict)

    for service_name, variable_name in (
        ("db", "SF_POSTGRES_IMAGE"),
        ("api", "SF_API_IMAGE"),
        ("worker", "SF_WORKER_IMAGE"),
        ("archive-sync", "SF_ARCHIVE_SYNC_IMAGE"),
        ("telegram-bot", "SF_BOT_IMAGE"),
    ):
        service = services[service_name]
        assert isinstance(service, dict)
        assert "build" not in service
        assert f"${{{variable_name}:?" in service["image"]


def test_deploy_workflow_is_manual_only() -> None:
    """Production deployment не стартует от завершения сборки образов."""
    workflow = _load_yaml(".github/workflows/deploy.yml")

    triggers = cast(dict[bool, dict[str, object]], workflow)[True]
    assert set(triggers) == {"workflow_dispatch"}


def test_ci_security_and_image_publication_have_separate_triggers() -> None:
    """PR/main проверяются без публикации; provenance/digest создаёт только release tag."""
    ci = _load_yaml(".github/workflows/ci.yml")
    security = _load_yaml(".github/workflows/security.yml")
    docker = _load_yaml(".github/workflows/docker.yml")

    ci_triggers = cast(dict[str, object], cast(dict[bool, object], ci)[True])
    security_triggers = cast(dict[str, object], cast(dict[bool, object], security)[True])
    docker_triggers = cast(dict[str, object], cast(dict[bool, object], docker)[True])
    assert "pull_request" in ci_triggers
    assert "main" in cast(dict[str, list[str]], ci_triggers["push"])["branches"]
    assert "pull_request" in security_triggers
    docker_push = cast(dict[str, list[str]], docker_triggers["push"])
    assert docker_push == {"tags": ["v*.*.*"]}
    docker_text = (PROJECT_ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8")
    assert "type=raw,value=latest" not in docker_text
    assert "type=sha,prefix=" not in docker_text


def test_caddy_does_not_publish_internal_metrics() -> None:
    """Public ingress не проксирует endpoint метрик API."""
    caddyfile = (PROJECT_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

    assert "@internal_metrics path /metrics /metrics/*" in caddyfile
    assert "respond @internal_metrics 404" in caddyfile
    public_compose = _load_yaml("docker-compose.public.yml")
    public_services = cast(dict[str, dict[str, object]], public_compose["services"])
    caddy = public_services["caddy"]
    assert caddy["ports"] == ["80:80", "443:443"]
    assert (
        "${SF_API_DOMAIN:?set SF_API_DOMAIN}" in cast(dict[str, str], caddy["environment"]).values()
    )


def test_worker_image_does_not_embed_training_data_or_models() -> None:
    """Runtime Worker получает data и models только через production volumes."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --chown=sf:sf data/ ./data/" not in dockerfile
    assert "COPY --chown=sf:sf models/ ./models/" not in dockerfile


def test_runtime_images_use_fixed_non_root_identity() -> None:
    """Все runtime targets используют выделенные непривилегированные UID/GID."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "groupadd --system --gid 10001 sf" in dockerfile
    assert "useradd --system --uid 10001 --gid sf" in dockerfile

    for target in ("api", "worker", "telegram-bot", "archive-sync"):
        stage = dockerfile.split(f"FROM base AS {target}", maxsplit=1)[1]
        stage_body = stage.split("\nFROM ", maxsplit=1)[0]
        assert "\nUSER sf\n" in stage_body


def test_runtime_base_applies_available_os_security_updates() -> None:
    """Runtime image получает fixed Debian packages до установки системных deps."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "apt-get update && \\\n"
        "    apt-get upgrade -y --no-install-recommends && \\\n"
        "    apt-get install"
    ) in dockerfile


def test_production_dependencies_exclude_local_training_control_plane() -> None:
    """Runtime image не устанавливает DVC, MLflow и Optuna из базовой группы."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert isinstance(dependencies, list)
    dependency_names = {
        str(dependency).split("[", maxsplit=1)[0].split("=", maxsplit=1)[0]
        for dependency in dependencies
    }
    assert {"dvc", "dvc-s3", "mlflow", "optuna"}.isdisjoint(dependency_names)


def test_production_services_receive_only_scoped_runtime_access() -> None:
    """Reader, bot и refresh worker не разделяют лишние mounts и credentials."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = cast(dict[str, dict[str, object]], compose["services"])

    api = services["api"]
    bot = services["telegram-bot"]
    worker = services["worker"]
    source_acquirer = services["source-acquirer"]
    archive_sync = services["archive-sync"]

    assert api["environment"] == {
        "DATABASE_URL_FILE": "/run/secrets/api_database_url",
        "SF_CONTROL_DATABASE_URL_FILE": "/run/secrets/control_database_url",
        "SF_CONTROL_API_KEY_FILE": "/run/secrets/control_api_key",
        "SF_CONTROL_ADMIN_IDS": "${BOT_ADMIN_USER_IDS:-}",
        "SF_DATA_CYCLE_NOTIFICATION_ALIASES": (
            "${SF_DATA_CYCLE_NOTIFICATION_ALIASES:?set safe notification aliases}"
        ),
    }
    assert "volumes" not in api
    assert "volumes" not in bot
    assert "DATABASE_URL" not in cast(dict[str, str], bot["environment"])
    bot_environment = cast(dict[str, str], bot["environment"])
    assert bot_environment["BOT_TOKEN_FILE"] == "/run/secrets/bot_token"
    assert bot_environment["BOT_CONTROL_API_KEY_FILE"] == "/run/secrets/control_api_key"
    assert bot_environment["BOT_NOTIFICATION_DESTINATIONS_FILE"] == (
        "/run/secrets/bot_notification_destinations"
    )
    assert "bot_notification_destinations" in cast(list[str], bot["secrets"])
    assert bot_environment["BOT_TELEGRAM_API_BASE_URL"] == "${BOT_TELEGRAM_API_BASE_URL:-}"
    assert worker["environment"] == {
        "DATABASE_URL_FILE": "/run/secrets/worker_database_url",
        "SF_WORKER_RUN_ID": "${SF_WORKER_RUN_ID:?set a scheduler-generated id}",
        "SF_DATA_CYCLE_NOTIFICATION_ALIASES": (
            "${SF_DATA_CYCLE_NOTIFICATION_ALIASES:?set safe notification aliases}"
        ),
        "SF_DATA_CYCLE_RUN_ID": "${SF_DATA_CYCLE_RUN_ID:-untracked}",
        "SF_DATA_CYCLE_GENERATION": "${SF_DATA_CYCLE_GENERATION:-0}",
        "SF_DATA_CYCLE_OWNER_ID": "${SF_DATA_CYCLE_OWNER_ID:-untracked}",
        "SF_MODEL_RUNTIME_ROOT": "/app/models",
        "SF_APP_VERSION": "${SF_APP_VERSION:?set SF_APP_VERSION}",
        "SF_CANONICAL_SOURCE_CSV": "/app/data/source/nhl/current.csv",
        "SF_OPERATIONAL_ARCHIVE_ROOT": "/app/archive",
    }
    assert worker["labels"] == {
        "com.sfp.data-cycle.run-id": "${SF_DATA_CYCLE_RUN_ID:-untracked}",
        "com.sfp.data-cycle.owner-generation": "${SF_DATA_CYCLE_GENERATION:-0}",
        "com.sfp.data-cycle.owner-id": "${SF_DATA_CYCLE_OWNER_ID:-untracked}",
    }
    assert worker["volumes"] == [
        "${SF_MODEL_RUNTIME_ROOT:?set SF_MODEL_RUNTIME_ROOT}:/app/models:ro",
        "${SF_CANONICAL_SOURCE_ROOT:?set SF_CANONICAL_SOURCE_ROOT}:/app/data/source/nhl:ro",
        "${SF_OPERATIONAL_ARCHIVE_ROOT:?set SF_OPERATIONAL_ARCHIVE_ROOT}:/app/archive",
    ]
    assert "SF_OBJECT_STORAGE_ACCESS_KEY_ID" not in cast(dict[str, str], worker["environment"])
    assert source_acquirer["environment"] == {
        "SF_DATA_CYCLE_RUN_ID": "${SF_DATA_CYCLE_RUN_ID:-untracked}",
        "SF_DATA_CYCLE_GENERATION": "${SF_DATA_CYCLE_GENERATION:-0}",
        "SF_DATA_CYCLE_OWNER_ID": "${SF_DATA_CYCLE_OWNER_ID:-untracked}",
        "SF_CANONICAL_SOURCE_SNAPSHOT": "/app/data/source/nhl/current.csv",
        "ODDS_API_KEY_FREE_FILE": "/run/secrets/odds_api_key_free",
        "ODDS_API_KEY_20K_FILE": "/run/secrets/odds_api_key_20k",
        "ODDS_API_KEY_100K_FILE": "/run/secrets/odds_api_key_100k",
        "ODDS_API_KEY_FILE": "/run/secrets/odds_api_key",
    }
    assert source_acquirer["volumes"] == [
        "${SF_CANONICAL_SOURCE_ROOT:?set SF_CANONICAL_SOURCE_ROOT}:/app/data/source/nhl",
    ]
    assert source_acquirer["labels"] == worker["labels"]
    assert archive_sync["labels"] == worker["labels"]
    assert archive_sync["profiles"] == ["operational-sync"]
    assert "entrypoint" not in archive_sync
    assert archive_sync["volumes"] == [
        "${SF_OPERATIONAL_ARCHIVE_ROOT:?set SF_OPERATIONAL_ARCHIVE_ROOT}:/app/archive:ro",
        "${SF_ARCHIVE_SYNC_STATE_ROOT:?set SF_ARCHIVE_SYNC_STATE_ROOT}:/app/sync-state",
    ]
    assert (
        cast(dict[str, str], archive_sync["environment"])["SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE"]
        == "/run/secrets/object_storage_access_key"
    )
    assert services["migrator"]["profiles"] == ["migration"]
    assert services["role-bootstrap"]["profiles"] == ["migration"]
    assert set(cast(dict[str, object], compose["volumes"])) == {"pg_data"}


def test_systemd_scheduler_has_durable_cycle_before_calendar_acquisition() -> None:
    """Business dispatcher и fixed run template подготавливают durable cycle."""
    service = (SYSTEMD_DIR / "sports-forecast-canonical-refresh@.service").read_text(
        encoding="utf-8"
    )
    timer = (SYSTEMD_DIR / "sports-forecast-canonical-refresh@.timer").read_text(encoding="utf-8")
    dispatcher_service = (SYSTEMD_DIR / "sports-forecast-data-cycle-dispatcher.service").read_text(
        encoding="utf-8"
    )
    dispatcher_timer = (SYSTEMD_DIR / "sports-forecast-data-cycle-dispatcher.timer").read_text(
        encoding="utf-8"
    )
    cycle_service = (SYSTEMD_DIR / "sports-forecast-data-cycle@.service").read_text(
        encoding="utf-8"
    )
    bridge = (SYSTEMD_DIR / "dispatch-data-cycle.sh").read_text(encoding="utf-8")
    runner = (SYSTEMD_DIR / "run-canonical-refresh.sh").read_text(encoding="utf-8")
    recovery = (SYSTEMD_DIR / "recover-data-cycle.sh").read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/sports-forecast/refresh/%i.env" in service
    assert "dispatch-data-cycle.sh %i" in service
    assert "OnBootSec=365d" in timer
    assert "OnUnitActiveSec=60s" in dispatcher_timer
    assert "dispatch-data-cycle.sh nhl" in dispatcher_service
    assert "data-cycle-dispatcher" in bridge
    assert "systemctl start --no-block" in bridge
    assert "recover-data-cycle.sh" in bridge
    assert "owner-info --run-id" in recovery
    assert "docker ps -aq" in recovery
    assert "docker stop --time 10" in recovery
    assert 'unit="sports-forecast-data-cycle@${run_id}.service"' in recovery
    assert "inventory_complete" in recovery
    assert "sports-forecast-data-cycle@${run_id}.service" in bridge
    assert 'pipeline" != "nhl"' in bridge
    assert "EnvironmentFile=/etc/sports-forecast/refresh/nhl.env" in cycle_service
    assert "run-canonical-refresh.sh nhl %i" in cycle_service
    assert "TimeoutStartSec=90m" in cycle_service
    assert "flock -n" in cycle_service
    assert "canonical_full_refresh_cli" in runner
    assert "source_snapshot_cli" in runner
    assert runner.index("source_snapshot_cli") < runner.index("canonical_full_refresh_cli")
    assert "archive-sync" in runner
    assert runner.index("canonical_full_refresh_cli") < runner.index("archive-sync")
    assert "SF_NHL_SOURCE_STATE_PREFIX" in runner
    assert "SF_WORKER_RUN_ID" in runner
    assert "claim --run-id" in runner
    assert "SF_DATA_CYCLE_GENERATION" in runner
    assert "data_cycle_cli" in runner
    assert "--calendar-attempt" in runner
    assert "finish-run" in runner
    assert "run_with_heartbeat()" in runner
    assert runner.count("run_with_heartbeat /usr/bin/docker compose") >= 3
    heartbeat_guard = (SYSTEMD_DIR / "data-cycle-owner-guard.sh").read_text(encoding="utf-8")
    assert "control heartbeat --run-id" in heartbeat_guard
    assert "data_cycle_mark_recovery_required" in heartbeat_guard
    assert "host recovery must prove stage stop" in runner
    assert 'source "${script_dir}/data-cycle-owner-guard.sh"' in runner
    assert "trap 'data_cycle_handle_signal 143' TERM" in runner
    assert "trap 'data_cycle_handle_signal 130' INT" in runner
    assert runner.index("data_cycle_mark_claim_attempted") < runner.index(
        'generation="$(control claim'
    )
    assert "Unit=sports-forecast-canonical-refresh@%i.service" in timer


def test_executor_term_does_not_terminalize_before_host_stop_proof(tmp_path: Path) -> None:
    """TERM during/after claim leaves terminal failure to verified host recovery."""
    guard = shlex.quote(str(SYSTEMD_DIR / "data-cycle-owner-guard.sh"))
    fail_marker = shlex.quote(str(tmp_path / "terminal-fail-called"))
    ready_marker = shlex.quote(str(tmp_path / "executor-ready"))
    script = f"""
set -euo pipefail
source {guard}
control() {{ touch {fail_marker}; }}
on_exit() {{
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    if data_cycle_should_defer_terminal_failure; then exit "${{result}}"; fi
    control fail
  fi
  exit "${{result}}"
}}
trap on_exit EXIT
trap 'data_cycle_handle_signal 143' TERM
data_cycle_mark_claim_attempted
touch {ready_marker}
sleep 30 >/dev/null 2>&1 &
wait $!
"""
    process = subprocess.Popen(
        ["bash", "-c", script],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    ready = tmp_path / "executor-ready"
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists(), "harness did not reach claimed-owner state"
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=5)

    assert process.returncode != 0
    assert not (tmp_path / "terminal-fail-called").exists()


def test_failed_compose_client_with_live_container_defers_terminal_failure(
    tmp_path: Path,
) -> None:
    """Nonzero client status is not proof that its one-off container stopped."""
    guard = shlex.quote(str(SYSTEMD_DIR / "data-cycle-owner-guard.sh"))
    fail_marker = shlex.quote(str(tmp_path / "terminal-fail-called"))
    live_container = shlex.quote(str(tmp_path / "container-still-live"))
    script = f"""
set -euo pipefail
source {guard}
control() {{ touch {fail_marker}; }}
on_exit() {{
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    if data_cycle_should_defer_terminal_failure; then exit "${{result}}"; fi
    control fail
  fi
  exit "${{result}}"
}}
trap on_exit EXIT
data_cycle_mark_claim_attempted
fake_compose_client() {{ touch {live_container}; return 42; }}
data_cycle_run_with_heartbeat fake_compose_client
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 42
    assert (tmp_path / "container-still-live").exists()
    assert not (tmp_path / "terminal-fail-called").exists()


def test_fast_compose_success_does_not_wait_for_heartbeat_tick(tmp_path: Path) -> None:
    """Короткая завершившаяся стадия не ждёт polling интервал heartbeat."""
    guard = shlex.quote(str(SYSTEMD_DIR / "data-cycle-owner-guard.sh"))
    heartbeat_marker = shlex.quote(str(tmp_path / "heartbeat-called"))
    script = f"""
set -euo pipefail
source {guard}
control() {{ touch {heartbeat_marker}; }}
SF_WORKER_RUN_ID=run-fast
fake_compose_client() {{ return 0; }}
data_cycle_run_with_heartbeat fake_compose_client
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert not (tmp_path / "heartbeat-called").exists()


def test_fast_compose_error_returns_without_heartbeat_hang(tmp_path: Path) -> None:
    """Короткая ошибка стадии сразу возвращается и оставляет recovery-required."""
    guard = shlex.quote(str(SYSTEMD_DIR / "data-cycle-owner-guard.sh"))
    recovery_marker = shlex.quote(str(tmp_path / "recovery-required"))
    script = f"""
set -euo pipefail
source {guard}
data_cycle_mark_recovery_required() {{ data_cycle_recovery_required=1; touch {recovery_marker}; }}
control() {{ return 0; }}
SF_WORKER_RUN_ID=run-fast-error
data_cycle_mark_claim_attempted
fake_compose_client() {{ return 23; }}
data_cycle_run_with_heartbeat fake_compose_client
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 23
    assert (tmp_path / "recovery-required").exists()


def test_scheduler_profile_template_keeps_schedule_and_secrets_outside_repository() -> None:
    """Каждый tournament profile задаёт cadence и scoped credentials в host drop-in."""
    profile = (SYSTEMD_DIR / "refresh-profile.env.example").read_text(encoding="utf-8")
    schedule = (SYSTEMD_DIR / "schedule.conf.example").read_text(encoding="utf-8")
    runtime = (SYSTEMD_DIR / "runtime.conf.example").read_text(encoding="utf-8")

    assert "SF_WORKER_DATABASE_URL_FILE=" in profile
    assert "SF_CANONICAL_SOURCE_ROOT=" in profile
    assert "SF_OPERATIONAL_ARCHIVE_ROOT=" in profile
    assert "SF_API_DATABASE_URL_FILE=" in profile
    assert "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY=" not in profile
    assert "OnCalendar=*-*-* 10:00:00 Europe/Moscow" in schedule
    assert "TimeoutStartSec=90m" in runtime


def test_scheduler_profile_provides_every_production_compose_input() -> None:
    """Scheduler profile не должен падать на interpolation inactive Compose services."""
    profile = (SYSTEMD_DIR / "refresh-profile.env.example").read_text(encoding="utf-8")
    names = {
        line.split("=", maxsplit=1)[0]
        for line in profile.splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert {
        "SF_POSTGRES_PASSWORD_FILE",
        "SF_API_DB_PASSWORD_FILE",
        "SF_WORKER_DB_PASSWORD_FILE",
        "SF_MIGRATOR_DB_PASSWORD_FILE",
        "SF_CONTROL_API_DB_PASSWORD_FILE",
        "SF_MIGRATOR_DATABASE_URL_FILE",
        "SF_CONTROL_DATABASE_URL_FILE",
        "SF_CONTROL_API_KEY_FILE",
        "SF_DATA_CYCLE_DISPATCHER_ID",
        "BOT_ADMIN_USER_IDS",
        "SF_BOT_TOKEN_FILE",
        "ODDS_API_KEY_FREE_FILE",
        "ODDS_API_KEY_20K_FILE",
        "ODDS_API_KEY_100K_FILE",
        "ODDS_API_KEY_FILE",
        "SF_ARCHIVE_SYNC_IMAGE",
        "SF_ARCHIVE_SYNC_STATE_ROOT",
        "SF_OBJECT_STORAGE_ENDPOINT",
        "SF_OBJECT_STORAGE_BUCKET",
        "SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE",
        "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE",
        "SF_WORKER_RUN_ID",
    }.issubset(names)


def test_runtime_healthcheck_uses_readiness_and_persistent_state_is_declared() -> None:
    """Compose проверяет готовность DB, а API image проверяет DB-aware readiness."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = cast(dict[str, dict[str, object]], compose["services"])
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert services["db"]["healthcheck"]
    assert services["api"]["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert "curl -f http://localhost:8000/ready" in dockerfile
    assert set(cast(dict[str, object], compose["volumes"])) == {"pg_data"}
