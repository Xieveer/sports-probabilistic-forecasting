"""Data Cycle durable lifecycle tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.orchestration import data_cycle as data_cycle_service
from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import (
    Base,
    CalendarCoverage,
)
from sports_forecast.service.db.repository import DataCycleRunRepository
from sports_forecast.service.routers import calendar as calendar_router


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_run_has_durable_waiting_stages_and_terminal_summary(session: Session) -> None:
    now = datetime(2026, 9, 26, 10, tzinfo=UTC).replace(tzinfo=None)
    repo = DataCycleRunRepository(session)

    run = repo.create(run_id="run-a", tournament="nhl", reason="scheduled", at=now)
    assert run.status == "waiting"
    assert {stage.stage for stage in run.stages} == {
        "calendar",
        "data_odds",
        "quality",
        "predictions",
        "publication",
        "archive_sync",
    }
    repo.start_stage("run-a", "calendar", at=now)
    repo.finish_stage("run-a", "calendar", status="success", at=now, counts={"events": 24})
    repo.finish_run("run-a", status="partial_success", at=now, summary={"events": 24})

    stored = repo.get("run-a")
    assert stored is not None
    assert stored.status == "partial_success"
    assert stored.summary_json == '{"events":24}'
    calendar = next(stage for stage in stored.stages if stage.stage == "calendar")
    assert calendar.status == "success"
    assert calendar.counts_json == '{"events":24}'


def test_failed_calendar_attempt_invalidates_old_successful_coverage(monkeypatch) -> None:
    checked = datetime(2026, 9, 26, 10, tzinfo=UTC).replace(tzinfo=None)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    last_success = datetime(2026, 9, 25, 12)
    with Session(engine) as session:
        old = CalendarCoverage(
            tournament="nhl",
            source="nhl_web_api",
            covered_from=datetime(2026, 9, 26),
            covered_until=datetime(2026, 10, 26),
            complete=True,
            checked_at=last_success,
            last_successful_at=last_success,
        )
        session.add(old)
        repo = DataCycleRunRepository(session)
        repo.create(run_id="run-fetch-failure", tournament="nhl", reason="scheduled")
        repo.start_stage("run-fetch-failure", "calendar", at=checked)
        session.commit()

    @contextmanager
    def test_session():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(calendar_router, "get_session", test_session)
    monkeypatch.setattr(data_cycle_service, "get_session", test_session)
    monkeypatch.setattr(calendar_router, "utc_now", lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))
    data_cycle_service.fail_run(
        "run-fetch-failure", failure_code="source_fetch_failed", tournament="nhl"
    )

    with TestClient(app_module.app) as client:
        response = client.get("/calendar/nhl", params={"period": "30"})

    assert response.status_code == 200
    assert response.json()["coverage"]["status"] == "unavailable"
    assert response.json()["coverage"]["last_successful_at"] == "2026-09-25T12:00:00Z"
    with Session(engine) as session:
        coverage = session.scalar(select(CalendarCoverage))
        assert coverage is not None
        assert coverage.failure_code == "source_fetch_failed"
        api_checked_at = datetime.fromisoformat(
            response.json()["coverage"]["checked_at"].replace("Z", "+00:00")
        )
        assert api_checked_at.replace(tzinfo=None) == coverage.checked_at
        assert coverage.checked_at > last_success
        assert coverage.covered_until == datetime(2026, 10, 26)
        run = DataCycleRunRepository(session).get("run-fetch-failure")
        assert run is not None and run.status == "failed"
        calendar_stage = next(stage for stage in run.stages if stage.stage == "calendar")
        assert calendar_stage.status == "failed"
    engine.dispose()


def test_only_one_nonterminal_run_per_tournament(session: Session) -> None:
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="manual")
    with pytest.raises(IntegrityError):
        repo.create(run_id="run-b", tournament="nhl", reason="manual")


def test_unknown_stage_and_reason_are_rejected(session: Session) -> None:
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="manual")
    with pytest.raises(ValueError):
        repo.start_stage("run-a", "untrusted command")
    with pytest.raises(ValueError):
        repo.fail_run("run-a", failure_code="provider payload: secret", at=datetime.now(UTC))


def test_stage_cannot_succeed_before_start(session: Session) -> None:
    """Waiting stage не должна получить success без фактического выполнения."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="scheduled")

    with pytest.raises(ValueError, match="должна быть running"):
        repo.finish_stage("run-a", "calendar", status="success")


def test_run_cannot_finish_while_stage_is_running(session: Session) -> None:
    """Terminal run не оставляет вечную running стадию."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="scheduled")
    repo.start_stage("run-a", "calendar")

    with pytest.raises(ValueError, match="работающей стадии"):
        repo.finish_run("run-a", status="partial_success")

    run = repo.get("run-a")
    assert run is not None and run.status == "running"
    assert run.current_stage == "calendar"


@pytest.mark.parametrize(
    ("stage_name", "expected_failure_code"),
    [
        ("calendar", "source_fetch_failed"),
        ("data_odds", "odds_acquisition_failed"),
        ("quality", "quality_failed"),
        ("predictions", "prediction_failed"),
        ("publication", "publication_failed"),
        ("archive_sync", "archive_sync_failed"),
    ],
)
def test_executor_failure_code_uses_current_stage(
    session: Session, stage_name: str, expected_failure_code: str
) -> None:
    """Executor trap attributes failure to current stage, not shell phase."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="scheduled")
    repo.start_stage("run-a", stage_name)

    repo.fail_run("run-a", failure_code="executor_interrupted")

    run = repo.get("run-a")
    assert run is not None
    assert run.status == "failed"
    assert run.failure_code == expected_failure_code
    stage = next(result for result in run.stages if result.stage == stage_name)
    assert stage.status == "failed"
    assert stage.failure_code == expected_failure_code
