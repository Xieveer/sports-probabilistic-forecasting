"""Контракты безопасного execution state одноразового Worker."""

from __future__ import annotations

from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import WorkerExecutionRepository


def test_completed_run_is_idempotent_and_stores_only_safe_summary() -> None:
    """Повтор scheduler run не создаёт второй publish и не хранит payload."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            state = WorkerExecutionRepository(session)
            assert state.start("daily-2026-08-09") is True
            state.succeed("daily-2026-08-09", predictions_count=2)

        with get_session(engine=engine) as session:
            state = WorkerExecutionRepository(session)
            assert state.start("daily-2026-08-09") is False
            latest = state.get("daily-2026-08-09")
            assert latest is not None
            assert latest.status == "succeeded"
            assert latest.predictions_count == 2
            assert latest.failure_code is None
    finally:
        reset_engine()
        engine.dispose()


def test_failed_run_stores_code_without_exception_text() -> None:
    """Execution state не переносит секреты или внешний payload в БД."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            state = WorkerExecutionRepository(session)
            state.start("daily-2026-08-10")
            state.fail("daily-2026-08-10", failure_code="bundle_verification_failed")
            latest = state.get("daily-2026-08-10")
            assert latest is not None
            assert latest.status == "failed"
            assert latest.failure_code == "bundle_verification_failed"
    finally:
        reset_engine()
        engine.dispose()
