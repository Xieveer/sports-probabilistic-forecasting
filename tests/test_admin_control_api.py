"""HTTP contract tests for protected Data Cycle control API."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import Base
from sports_forecast.service.db.repository import DataCycleRunRepository
from sports_forecast.service.routers import admin_control


@pytest.fixture
def control_client(monkeypatch, tmp_path: Path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    key_file = tmp_path / "control_api_key"
    key_file.write_text("test-control-secret", encoding="utf-8")
    monkeypatch.setenv("SF_CONTROL_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("SF_CONTROL_ADMIN_IDS", "101,202")

    @contextmanager
    def control_session():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(admin_control, "get_control_session", control_session)
    with TestClient(app_module.app) as client:
        yield client, engine
    engine.dispose()


def _headers(*, service_key: str = "test-control-secret", admin_id: str = "101") -> dict[str, str]:
    return {
        "X-Control-Service-Key": service_key,
        "X-Telegram-Admin-Id": admin_id,
    }


def test_control_routes_deny_empty_or_invalid_auth(control_client, monkeypatch) -> None:
    client, _engine = control_client
    response = client.get("/admin/pipelines", headers={"X-Telegram-Admin-Id": "101"})
    assert response.status_code == 403

    response = client.get("/admin/pipelines", headers=_headers(service_key="wrong"))
    assert response.status_code == 403

    response = client.get("/admin/pipelines", headers=_headers(admin_id="999"))
    assert response.status_code == 403

    monkeypatch.delenv("SF_CONTROL_ADMIN_IDS")
    response = client.get("/admin/pipelines", headers=_headers())
    assert response.status_code == 403


def test_schedule_is_persistent_and_uses_optimistic_revision(control_client) -> None:
    client, _engine = control_client
    response = client.get("/admin/pipelines/nhl/schedule", headers=_headers())
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["base_time"] == "10:00"
    assert response.json()["interval_hours"] == 24
    assert response.json()["revision"] == 1

    response = client.patch(
        "/admin/pipelines/nhl/schedule",
        headers=_headers(),
        json={
            "expected_revision": 1,
            "enabled": True,
            "base_time": "10:00",
            "timezone": "Europe/Moscow",
            "interval_hours": 6,
        },
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["interval_hours"] == 6

    stale = client.patch(
        "/admin/pipelines/nhl/schedule",
        headers=_headers(),
        json={
            "expected_revision": 1,
            "enabled": False,
            "base_time": "10:00",
            "timezone": "Europe/Moscow",
            "interval_hours": 6,
        },
    )
    assert stale.status_code == 409
    persisted = client.get("/admin/pipelines/nhl/schedule", headers=_headers()).json()
    assert persisted["enabled"] is True
    assert persisted["revision"] == 2


def test_manual_run_is_idempotent_and_active_run_is_not_duplicated(control_client) -> None:
    client, engine = control_client
    schedule_off = client.patch(
        "/admin/pipelines/nhl/schedule",
        headers=_headers(),
        json={
            "expected_revision": 1,
            "enabled": False,
            "base_time": "10:00",
            "timezone": "Europe/Moscow",
            "interval_hours": 24,
        },
    )
    assert schedule_off.status_code == 200
    assert schedule_off.json()["next_run_at"] is None

    invalid_key = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update 42 callback"},
    )
    assert invalid_key.status_code == 400

    first = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update-42-callback-1"},
    )
    assert first.status_code == 202
    assert first.json()["created"] is True
    run_id = first.json()["run_id"]

    retry = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update-42-callback-1"},
    )
    assert retry.status_code == 202
    assert retry.json()["run_id"] == run_id
    assert retry.json()["created"] is False

    second_key = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update-43-callback-1"},
    )
    assert second_key.status_code == 202
    assert second_key.json()["run_id"] == run_id
    assert second_key.json()["active_run"] is True

    with Session(engine) as session:
        DataCycleRunRepository(session).fail_run(run_id, failure_code="executor_interrupted")
        session.commit()

    terminal_retry = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update-42-callback-1"},
    )
    assert terminal_retry.status_code == 202
    assert terminal_retry.json()["run_id"] == run_id
    assert terminal_retry.json()["active_run"] is False

    pipeline_state = client.get("/admin/pipelines", headers=_headers()).json()["pipelines"][0]
    assert pipeline_state["current_run"] is None
    assert pipeline_state["last_run"]["run_id"] == run_id
    assert pipeline_state["last_run"]["status"] == "failed"

    retry_after_failure = client.post(
        "/admin/pipelines/nhl/runs",
        headers={**_headers(), "Idempotency-Key": "update-44-callback-1"},
    )
    assert retry_after_failure.status_code == 202
    assert retry_after_failure.json()["run_id"] != run_id
    assert retry_after_failure.json()["reason"] == "manual"


def test_control_secret_file_is_required_and_admin_routes_are_not_publicly_routed() -> None:
    caddyfile = Path("deploy/Caddyfile").read_text(encoding="utf-8")
    assert "@admin_control path /admin /admin/*" in caddyfile
    assert "respond @admin_control 404" in caddyfile
