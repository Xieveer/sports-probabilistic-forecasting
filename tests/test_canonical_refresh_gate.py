"""Durable lifecycle canonical freshness gate."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.orchestration.canonical_refresh_gate import run_canonical_freshness_gate
from sports_forecast.service.db.models import (
    Base,
    Prediction,
    RefreshFailureAlert,
    RefreshLock,
    WorkerExecution,
)


def test_failed_canonical_gate_is_idempotent_and_stores_safe_code() -> None:
    """Один run ID не создаёт повторный failure lifecycle."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        session.add(
            Prediction(
                match_id="1",
                tournament="nhl",
                market="winner",
                market_spec="winner_withOT",
                model_version="x",
                algorithm="x",
                featureset="x",
                predictions_json="{}",
                match_datetime=datetime(2026, 8, 14, 10, 0),
            )
        )
        session.commit()
        first = run_canonical_freshness_gate(
            session=session,
            run_id="nhl-20260814",
            tournament="nhl",
            refreshed_at=datetime(2026, 8, 14, 14, tzinfo=UTC),
            match_duration_minutes=210,
            provider_grace_minutes=30,
        )
        second = run_canonical_freshness_gate(
            session=session,
            run_id="nhl-20260814",
            tournament="nhl",
            refreshed_at=datetime(2026, 8, 14, 14, tzinfo=UTC),
            match_duration_minutes=210,
            provider_grace_minutes=30,
        )
        assert first.passed is False
        assert second.already_finished is True
        state = session.query(WorkerExecution).one()
        assert state.status == "failed"
        assert state.failure_code == "canonical_freshness_failed"
        alert = session.query(RefreshFailureAlert).one()
        assert alert.run_id == "nhl-20260814"
        assert alert.failure_code == "canonical_freshness_failed"
        assert alert.status == "pending"
    finally:
        session.close()


def test_occupied_tournament_lock_does_not_create_second_execution() -> None:
    """Конкурентный scheduler run останавливается до execution/alert side effects."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        session.add(RefreshLock(tournament="nhl", run_id="owner"))
        session.commit()
        outcome = run_canonical_freshness_gate(
            session=session,
            run_id="blocked",
            tournament="nhl",
            refreshed_at=datetime(2026, 8, 14, tzinfo=UTC),
            match_duration_minutes=210,
            provider_grace_minutes=30,
        )
        assert outcome.already_finished is True
        assert session.query(WorkerExecution).count() == 0
        assert session.query(RefreshFailureAlert).count() == 0
    finally:
        session.close()
