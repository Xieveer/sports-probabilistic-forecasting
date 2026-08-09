"""Контракт минимального production Compose и ручного deployment."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SERVICES = {"api", "db", "telegram-bot", "worker", "caddy"}


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
        ("api", "SF_API_IMAGE"),
        ("worker", "SF_WORKER_IMAGE"),
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
