"""Durable DB lifecycle для canonical freshness gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from sports_forecast.service.db.models import RefreshFailureAlert
from sports_forecast.service.db.refresh_lock import RefreshLockRepository
from sports_forecast.service.db.repository import WorkerExecutionRepository
from sports_forecast.validation.canonical_freshness import validate_prediction_result_freshness


@dataclass(frozen=True)
class CanonicalGateOutcome:
    """Безопасный outcome gate без provider payload или exception text."""

    passed: bool
    already_finished: bool


def run_canonical_freshness_gate(
    *,
    session: Session,
    run_id: str,
    tournament: str,
    refreshed_at: datetime,
    match_duration_minutes: int,
    provider_grace_minutes: int,
) -> CanonicalGateOutcome:
    """Выполнить freshness gate не более одного раза для scheduler run ID."""
    executions = WorkerExecutionRepository(session)
    locks = RefreshLockRepository(session)
    if not locks.acquire(tournament=tournament, run_id=run_id):
        return CanonicalGateOutcome(passed=False, already_finished=True)
    if not executions.start(run_id):
        locks.release(tournament=tournament, run_id=run_id)
        return CanonicalGateOutcome(passed=False, already_finished=True)
    try:
        result = validate_prediction_result_freshness(
            session=session,
            tournament=tournament,
            refreshed_at=refreshed_at,
            match_duration_minutes=match_duration_minutes,
            provider_grace_minutes=provider_grace_minutes,
        )
        if result.is_valid:
            executions.succeed(run_id, predictions_count=0)
        else:
            executions.fail(run_id, failure_code="canonical_freshness_failed")
            session.add(
                RefreshFailureAlert(
                    run_id=run_id,
                    tournament=tournament,
                    failure_code="canonical_freshness_failed",
                    status="pending",
                )
            )
        return CanonicalGateOutcome(passed=result.is_valid, already_finished=False)
    finally:
        locks.release(tournament=tournament, run_id=run_id)
        session.commit()
