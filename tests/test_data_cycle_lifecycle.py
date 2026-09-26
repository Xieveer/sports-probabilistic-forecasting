"""Data Cycle durable lifecycle tests."""

from __future__ import annotations

import json
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
from sports_forecast.service.data_cycle_history import get_current_run, list_recent_runs
from sports_forecast.service.db.models import (
    Base,
    CalendarCoverage,
)
from sports_forecast.service.db.repository import DataCycleRunRepository
from sports_forecast.service.routers import calendar as calendar_router


NHL_REQUIRED_STAGES = frozenset(
    {"calendar", "quality", "predictions", "publication", "archive_sync"}
)
FOOTBALL_REQUIRED_STAGES = frozenset({"calendar", "quality", "predictions", "publication"})


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_nhl_required_stage_policy_is_loaded_from_tournament_config() -> None:
    """NHL required stages come from its selected profile config."""
    assert data_cycle_service.load_required_stages("nhl") == NHL_REQUIRED_STAGES


def _complete_pipeline(
    repo: DataCycleRunRepository,
    run_id: str,
) -> None:
    """Закрыть fixture стадии по policy, оставляя odds явно partial."""
    run = repo.get(run_id)
    assert run is not None
    for stage in ("calendar", "data_odds", "quality", "predictions", "publication", "archive_sync"):
        result = next(stage_result for stage_result in run.stages if stage_result.stage == stage)
        if result.status != "waiting":
            continue
        repo.start_stage(run_id, stage)
        repo.finish_stage(
            run_id,
            stage,
            status="partial_success" if stage == "data_odds" else "success",
        )


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
    _complete_pipeline(repo, "run-a")
    repo.finish_run(
        "run-a",
        status="partial_success",
        required_stages=NHL_REQUIRED_STAGES,
        at=now,
        summary={"events": 24},
    )

    stored = repo.get("run-a")
    assert stored is not None
    assert stored.status == "partial_success"
    assert json.loads(stored.summary_json or "{}")["events"] == 24
    dto = list_recent_runs(session, "nhl", limit=1)[0]
    assert dto["summary"]["events"] == json.loads(stored.summary_json or "{}")["events"]
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


def test_quality_failure_blocks_prediction_and_publication_stages(session: Session) -> None:
    """Quality failure terminally prevents the cycle from publishing predictions."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-quality-failure", tournament="football_fixture", reason="manual")
    repo.start_stage("run-quality-failure", "quality")
    repo.finish_stage(
        "run-quality-failure",
        "quality",
        status="failed",
        failure_code="quality_failed",
    )

    with pytest.raises(ValueError, match="quality"):
        repo.start_stage("run-quality-failure", "publication")


def test_successful_run_cannot_hide_a_failed_stage(session: Session) -> None:
    """Run status reflects mandatory failed stages and cannot claim success."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-failed-stage", tournament="nhl", reason="scheduled")
    repo.start_stage("run-failed-stage", "quality")
    repo.finish_stage("run-failed-stage", "quality", status="failed", failure_code="quality_failed")

    with pytest.raises(ValueError, match="failed"):
        repo.finish_run("run-failed-stage", status="success", required_stages=NHL_REQUIRED_STAGES)


def test_partial_success_cannot_hide_failed_required_publication(session: Session) -> None:
    """A partial outcome cannot hide a failed stage required by pipeline policy."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-pub-failed", tournament="nhl", reason="manual")
    repo.start_stage("run-pub-failed", "quality")
    repo.finish_stage("run-pub-failed", "quality", status="success")
    for stage in ("calendar", "data_odds", "predictions"):
        repo.start_stage("run-pub-failed", stage)
        repo.finish_stage(
            "run-pub-failed",
            stage,
            status="partial_success" if stage == "data_odds" else "success",
        )
    repo.start_stage("run-pub-failed", "publication")
    repo.finish_stage(
        "run-pub-failed", "publication", status="failed", failure_code="publication_failed"
    )

    with pytest.raises(ValueError, match="обязательн"):
        repo.finish_run(
            "run-pub-failed",
            status="partial_success",
            required_stages=NHL_REQUIRED_STAGES,
        )


def test_success_requires_every_stage_to_be_observed(session: Session) -> None:
    """No-work waiting runs cannot be auto-skipped into a successful result."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-no-work", tournament="nhl", reason="scheduled")

    with pytest.raises(ValueError, match="не выполнены"):
        repo.finish_run("run-no-work", status="success", required_stages=NHL_REQUIRED_STAGES)


def test_terminal_policy_is_generic_for_football_pipeline(session: Session) -> None:
    """A football profile can declare its own required stages safely."""
    repo = DataCycleRunRepository(session)
    run_id = "football-policy-run"
    repo.create(run_id=run_id, tournament="football_fixture", reason="manual")
    for stage in ("calendar", "quality", "predictions", "publication"):
        repo.start_stage(run_id, stage)
        repo.finish_stage(
            run_id,
            stage,
            status="partial_success" if stage == "predictions" else "success",
        )
    repo.start_stage(run_id, "data_odds")
    repo.finish_stage(run_id, "data_odds", status="partial_success")

    repo.finish_run(
        run_id,
        status="partial_success",
        required_stages=FOOTBALL_REQUIRED_STAGES,
    )

    assert get_current_run(session, "football_fixture") is None


def test_data_cycle_summary_preserves_unknown_counts_and_zero_denominator_as_na(
    session: Session,
) -> None:
    """Summary exposes known counters, filters unknown keys, and avoids 0/0 as success."""
    repo = DataCycleRunRepository(session)
    now = datetime(2026, 9, 26, 10, tzinfo=UTC).replace(tzinfo=None)
    repo.create(run_id="football-run", tournament="football_fixture", reason="manual", at=now)
    repo.start_stage("football-run", "calendar", at=now)
    repo.finish_stage(
        "football-run",
        "calendar",
        status="success",
        at=now,
        counts={"events": 5, "new_events": 2, "secret_token": 123},
    )
    _complete_pipeline(repo, "football-run")
    repo.finish_run(
        "football-run",
        status="partial_success",
        required_stages=FOOTBALL_REQUIRED_STAGES,
        at=now,
    )

    stored = repo.get("football-run")
    assert stored is not None
    summary = json.loads(stored.summary_json or "{}")
    assert summary["events_found"] == 5
    assert summary["new_events"] == 2
    assert summary["prediction_coverage"] == {
        "numerator": None,
        "denominator": None,
        "ratio": None,
    }
    assert "secret_token" not in summary
    persisted_summary = json.loads(stored.summary_json or "{}")
    persisted_summary["secret_token"] = 123
    stored.summary_json = json.dumps(persisted_summary)
    stored.failure_code = "provider response with token=secret"
    session.flush()
    dto = list_recent_runs(session, "football_fixture", limit=1)[0]
    assert dto["failure_code"] is None
    assert dto["summary"]["events_found"] == persisted_summary["events_found"]
    assert "secret_token" not in dto["summary"]
    calendar_stage = next(stage for stage in dto["stages"] if stage["stage"] == "calendar")
    assert calendar_stage["counts"] == {"events": 5, "new_events": 2}
    assert "summary_json" not in dto


def test_data_cycle_summary_reports_observed_prediction_coverage(session: Session) -> None:
    """Футбольный fixture использует общий знаменатель eligible событий."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="football-coverage", tournament="football_fixture", reason="manual")
    repo.start_stage("football-coverage", "quality")
    repo.finish_stage(
        "football-coverage", "quality", status="success", counts={"eligible_events": 4}
    )
    repo.start_stage("football-coverage", "predictions")
    repo.finish_stage(
        "football-coverage", "predictions", status="success", counts={"predictions": 3}
    )
    repo.finish_run(
        "football-coverage",
        status="partial_success",
        required_stages=frozenset({"quality", "predictions"}),
    )

    summary = list_recent_runs(session, "football_fixture", limit=1)[0]["summary"]

    assert summary["prediction_coverage"] == {"numerator": 3, "denominator": 4, "ratio": 0.75}


def test_supplemental_summary_cannot_override_stage_derived_coverage(session: Session) -> None:
    """CLI supplemental counters cannot make summary coverage internally inconsistent."""
    repo = DataCycleRunRepository(session)
    run_id = "football-summary-conflict"
    repo.create(run_id=run_id, tournament="football_fixture", reason="manual")
    repo.start_stage(run_id, "calendar")
    repo.finish_stage(run_id, "calendar", status="success", counts={"events": 5})
    repo.start_stage(run_id, "data_odds")
    repo.finish_stage(
        run_id,
        "data_odds",
        status="partial_success",
        counts={"independently_observed_events": 2},
    )
    repo.start_stage(run_id, "quality")
    repo.finish_stage(run_id, "quality", status="success", counts={"eligible_events": 4})
    repo.start_stage(run_id, "predictions")
    repo.finish_stage(run_id, "predictions", status="success", counts={"predictions": 3})
    repo.start_stage(run_id, "publication")
    repo.finish_stage(run_id, "publication", status="success")

    repo.finish_stage(run_id, "archive_sync", status="skipped")
    repo.finish_run(
        run_id,
        status="partial_success",
        required_stages=FOOTBALL_REQUIRED_STAGES,
        summary={
            "events_found": 1,
            "eligible_events": 1,
            "predictions_ready": 1,
            "errors": 99,
        },
    )

    summary = list_recent_runs(session, "football_fixture", limit=1)[0]["summary"]

    assert summary["events_found"] == 5
    assert summary["eligible_events"] == 4
    assert summary["predictions_ready"] == 3
    assert summary["prediction_coverage"] == {"numerator": 3, "denominator": 4, "ratio": 0.75}
    assert summary["errors"] == 0


def test_history_repository_returns_current_and_recent_runs(session: Session) -> None:
    """History lookup is tournament-generic and returns newest runs first."""
    repo = DataCycleRunRepository(session)
    first = datetime(2026, 9, 26, 10)
    repo.create(run_id="football-old", tournament="football_fixture", reason="scheduled", at=first)
    _complete_pipeline(repo, "football-old")
    repo.finish_run(
        "football-old",
        status="partial_success",
        required_stages=FOOTBALL_REQUIRED_STAGES,
        at=first,
    )
    repo.create(
        run_id="football-current",
        tournament="football_fixture",
        reason="manual",
        at=first.replace(hour=11),
    )

    current = get_current_run(session, "football_fixture")
    recent = list_recent_runs(session, "football_fixture", limit=2)

    assert current is not None and current["run_id"] == "football-current"
    assert [run["run_id"] for run in recent] == ["football-current", "football-old"]
    assert recent[0]["stages"]
    with pytest.raises(ValueError, match="от 1 до 50"):
        list_recent_runs(session, "football_fixture", limit=100)


def test_run_cannot_finish_while_stage_is_running(session: Session) -> None:
    """Terminal run не оставляет вечную running стадию."""
    repo = DataCycleRunRepository(session)
    repo.create(run_id="run-a", tournament="nhl", reason="scheduled")
    repo.start_stage("run-a", "calendar")

    with pytest.raises(ValueError, match="работающей стадии"):
        repo.finish_run("run-a", status="partial_success", required_stages=NHL_REQUIRED_STAGES)

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
    if stage_name in {"predictions", "publication"}:
        repo.start_stage("run-a", "quality")
        repo.finish_stage("run-a", "quality", status="success")
    repo.start_stage("run-a", stage_name)

    repo.fail_run("run-a", failure_code="executor_interrupted")

    run = repo.get("run-a")
    assert run is not None
    assert run.status == "failed"
    assert run.failure_code == expected_failure_code
    stage = next(result for result in run.stages if result.stage == stage_name)
    assert stage.status == "failed"
    assert stage.failure_code == expected_failure_code
    assert run.summary_json is not None
    assert json.loads(run.summary_json)["errors"] == 1
