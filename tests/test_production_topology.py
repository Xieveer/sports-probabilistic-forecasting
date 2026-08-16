"""Контракт минимального production Compose и ручного deployment."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SERVICES = {"api", "db", "telegram-bot", "worker", "caddy"}
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
    assert services["caddy"]["ports"] == ["80:80", "443:443"]


def test_production_runtime_images_are_external_and_immutable_inputs() -> None:
    """API, Worker и bot получают image reference извне и не собираются на VPS."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = compose["services"]
    assert isinstance(services, dict)

    for service_name, variable_name in (
        ("db", "SF_POSTGRES_IMAGE"),
        ("api", "SF_API_IMAGE"),
        ("worker", "SF_WORKER_IMAGE"),
        ("telegram-bot", "SF_BOT_IMAGE"),
        ("caddy", "SF_CADDY_IMAGE"),
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


def test_caddy_does_not_publish_internal_metrics() -> None:
    """Public ingress не проксирует endpoint метрик API."""
    caddyfile = (PROJECT_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

    assert "@internal_metrics path /metrics /metrics/*" in caddyfile
    assert "respond @internal_metrics 404" in caddyfile


def test_worker_image_does_not_embed_training_data_or_models() -> None:
    """Runtime Worker получает data и models только через production volumes."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --chown=sf:sf data/ ./data/" not in dockerfile
    assert "COPY --chown=sf:sf models/ ./models/" not in dockerfile


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

    assert api["environment"] == {
        "DATABASE_URL": "${SF_API_DATABASE_URL:?set SF_API_DATABASE_URL}",
    }
    assert "volumes" not in api
    assert "volumes" not in bot
    assert "DATABASE_URL" not in cast(dict[str, str], bot["environment"])
    assert worker["environment"] == {
        "DATABASE_URL": "${SF_WORKER_DATABASE_URL:?set SF_WORKER_DATABASE_URL}",
        "SF_WORKER_RUN_ID": "${SF_WORKER_RUN_ID:?set a scheduler-generated id}",
        "SF_MODEL_RUNTIME_ROOT": "/app/models",
        "SF_APP_VERSION": "${SF_APP_VERSION:?set SF_APP_VERSION}",
        "SF_CANONICAL_SOURCE_CSV": "/app/source/current.csv",
        "SF_OPERATIONAL_ARCHIVE_ROOT": "/app/archive",
    }
    assert worker["volumes"] == [
        "runtime_models:/app/models:ro",
        "${SF_CANONICAL_SOURCE_ROOT:?set SF_CANONICAL_SOURCE_ROOT}:/app/source:ro",
        "${SF_OPERATIONAL_ARCHIVE_ROOT:?set SF_OPERATIONAL_ARCHIVE_ROOT}:/app/archive",
    ]
    assert "SF_OBJECT_STORAGE_ACCESS_KEY_ID" not in cast(dict[str, str], worker["environment"])
    assert "serving_data" not in cast(dict[str, object], compose["volumes"])


def test_systemd_scheduler_has_profile_cadence_lock_timeout_retry_and_safe_run_id() -> None:
    """Template не допускает overlap и оставляет DB execution state сигналом успеха."""
    service = (SYSTEMD_DIR / "sports-forecast-canonical-refresh@.service").read_text(
        encoding="utf-8"
    )
    timer = (SYSTEMD_DIR / "sports-forecast-canonical-refresh@.timer").read_text(encoding="utf-8")
    runner = (SYSTEMD_DIR / "run-canonical-refresh.sh").read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/sports-forecast/refresh/%i.env" in service
    assert "TimeoutStartSec=90m" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=5m" in service
    assert "flock -n" in service
    assert "canonical_full_refresh_cli" in runner
    assert "uuidgen" in runner
    assert "SF_WORKER_RUN_ID" in runner
    assert "last successful run is stored in worker_executions" in runner
    assert "OnBootSec=365d" in timer
    assert "Persistent=true" in timer
    assert "Unit=sports-forecast-canonical-refresh@%i.service" in timer


def test_scheduler_profile_template_keeps_schedule_and_secrets_outside_repository() -> None:
    """Каждый tournament profile задаёт cadence и scoped credentials в host drop-in."""
    profile = (SYSTEMD_DIR / "refresh-profile.env.example").read_text(encoding="utf-8")
    schedule = (SYSTEMD_DIR / "schedule.conf.example").read_text(encoding="utf-8")
    runtime = (SYSTEMD_DIR / "runtime.conf.example").read_text(encoding="utf-8")

    assert "SF_WORKER_DATABASE_URL=" in profile
    assert "SF_CANONICAL_SOURCE_ROOT=" in profile
    assert "SF_OPERATIONAL_ARCHIVE_ROOT=" in profile
    assert "SF_API_DATABASE_URL=" in profile
    assert "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY" not in profile
    assert "OnCalendar=*-*-* 10:00:00 Europe/Moscow" in schedule
    assert "TimeoutStartSec=90m" in runtime


def test_runtime_healthcheck_uses_readiness_and_persistent_state_is_declared() -> None:
    """Compose проверяет готовность DB, а API image проверяет DB-aware readiness."""
    compose = _load_yaml("docker-compose.prod.yml")
    services = cast(dict[str, dict[str, object]], compose["services"])
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert services["db"]["healthcheck"]
    assert services["api"]["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert "curl -f http://localhost:8000/ready" in dockerfile
    assert {"pg_data", "runtime_models", "caddy_data", "caddy_config"}.issubset(
        cast(dict[str, object], compose["volumes"])
    )
