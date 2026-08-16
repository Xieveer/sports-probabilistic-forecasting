"""Контракты readiness и versioned schema migrations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from sports_forecast.service import app as app_module
from sports_forecast.service.db import engine as engine_module
from sports_forecast.service.db.models import Base
from sports_forecast.service.routers import health


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_health_is_liveness_when_database_is_unavailable(monkeypatch) -> None:
    """Liveness не зависит от доступности PostgreSQL."""

    def unavailable_session():
        raise OSError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(health, "get_session", unavailable_session)

    with TestClient(app_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db_connected"] is False


def test_ready_returns_service_unavailable_when_database_is_unavailable(monkeypatch) -> None:
    """Readiness требует обязательный SQL-пинг."""

    def unavailable_session():
        raise OSError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(health, "get_session", unavailable_session)

    with TestClient(app_module.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["db_connected"] is False


def test_ready_returns_ok_when_database_is_available() -> None:
    """Readiness отвечает успехом только после SQL-пинга обязательной БД."""
    with TestClient(app_module.app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db_connected"] is True


def test_api_startup_does_not_create_or_modify_schema(monkeypatch) -> None:
    """API startup не выполняет DDL: schema меняет только migration command."""
    engine_module.reset_engine()
    schema_calls: list[object] = []

    def record_create_all(*args: object, **kwargs: object) -> None:
        schema_calls.append((args, kwargs))

    monkeypatch.setattr(Base.metadata, "create_all", record_create_all)

    with TestClient(app_module.app):
        pass

    assert schema_calls == []


def test_production_worker_does_not_initialize_schema() -> None:
    """Materialization Worker полагается на отдельную migration command."""
    worker_source = (PROJECT_ROOT / "sports_forecast/materialize.py").read_text(encoding="utf-8")

    assert "init_db" not in worker_source


def test_migration_command_creates_schema_and_is_idempotent(tmp_path: Path) -> None:
    """Версионированная migration создаёт schema и безопасно повторяется."""
    database_path = tmp_path / "migration.db"
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path}",
    }
    command = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"]

    first_run = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    second_run = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr

    migrated_engine = engine_module.create_engine(f"sqlite:///{database_path}")
    try:
        table_names = set(inspect(migrated_engine).get_table_names())
    finally:
        migrated_engine.dispose()

    assert {
        "alembic_version",
        "predictions",
        "notification_line_states",
        "notification_cycles",
        "notification_deliveries",
        "model_deployments",
        "lineup_prediction_revisions",
        "lineup_notification_outbox",
        "canonical_events",
        "canonical_event_revisions",
        "refresh_watermarks",
        "bootstrap_imports",
    } <= table_names
