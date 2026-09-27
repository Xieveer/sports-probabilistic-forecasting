"""Integration checks for least-privilege runtime Postgres identities."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from sports_forecast.service.db.repository import DataCycleNotificationOutboxRepository


@pytest.mark.integration
@pytest.mark.skipif(
    not (
        os.environ.get("SF_TEST_CONTROL_DATABASE_URL")
        and os.environ.get("SF_TEST_API_READER_DATABASE_URL")
    ),
    reason="Задайте runtime DB URLs на disposable PostgreSQL для grants tests",
)
def test_control_and_reader_roles_cannot_cross_their_database_boundaries() -> None:
    """Control читает только цикл и не завершает его; API reader не видит control state."""
    control_engine = create_engine(os.environ["SF_TEST_CONTROL_DATABASE_URL"])
    reader_engine = create_engine(os.environ["SF_TEST_API_READER_DATABASE_URL"])
    try:
        with control_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM data_cycle_runs")).scalar_one() >= 0
            )
            with pytest.raises(SQLAlchemyError):
                connection.execute(text("SELECT count(*) FROM predictions")).scalar_one()
            connection.rollback()
            with pytest.raises(SQLAlchemyError):
                connection.execute(text("UPDATE data_cycle_runs SET status='success' WHERE false"))
            connection.rollback()
            with pytest.raises(SQLAlchemyError):
                connection.execute(
                    text("UPDATE data_cycle_runs SET executor_stalled_at=NULL WHERE false")
                )
            connection.rollback()
            assert (
                connection.execute(
                    text("SELECT public.mark_data_cycle_executor_stalled('missing-run')")
                ).scalar_one()
                is False
            )

        with reader_engine.connect() as connection, pytest.raises(SQLAlchemyError):
            connection.execute(
                text("SELECT count(*) FROM data_cycle_control_requests")
            ).scalar_one()
    finally:
        control_engine.dispose()
        reader_engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    not (
        os.environ.get("SF_TEST_CONTROL_DATABASE_URL")
        and os.environ.get("SF_TEST_API_READER_DATABASE_URL")
        and os.environ.get("SF_TEST_REFRESH_WRITER_DATABASE_URL")
    ),
    reason=(
        "Задайте control/reader/refresh-writer URLs на disposable PostgreSQL "
        "для notification outbox grants tests"
    ),
)
def test_control_role_claims_outbox_but_cannot_write_terminal_state_or_sequence() -> None:
    """Control использует outbox columns, а terminal producer остаётся worker-only."""
    control_engine = create_engine(os.environ["SF_TEST_CONTROL_DATABASE_URL"])
    reader_engine = create_engine(os.environ["SF_TEST_API_READER_DATABASE_URL"])
    worker_engine = create_engine(os.environ["SF_TEST_REFRESH_WRITER_DATABASE_URL"])
    run_id = f"runtime-outbox-{uuid4()}"
    now = "2026-09-27 08:00:00"
    try:
        with worker_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO data_cycle_runs "
                    "(run_id, tournament, reason, status, failure_code, requested_at, completed_at) "
                    "VALUES (:run_id, 'nhl', 'manual', 'failed', 'source_fetch_failed', "
                    ":now, :now)"
                ),
                {"run_id": run_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO data_cycle_notification_outbox "
                    "(run_id, destination_alias, status, attempts, available_at) "
                    "VALUES (:run_id, 'nhl_admins', 'pending', 0, :now)"
                ),
                {"run_id": run_id, "now": now},
            )

        with control_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM data_cycle_notification_outbox WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                ).scalar_one()
                == 1
            )
            with pytest.raises(SQLAlchemyError):
                connection.execute(
                    text("UPDATE data_cycle_runs SET status='success' WHERE run_id=:run_id"),
                    {"run_id": run_id},
                )
            connection.rollback()
            with pytest.raises(SQLAlchemyError):
                connection.execute(
                    text("SELECT nextval('data_cycle_notification_outbox_id_seq')")
                ).scalar_one()
            connection.rollback()
            with pytest.raises(SQLAlchemyError):
                connection.execute(
                    text(
                        "INSERT INTO data_cycle_notification_outbox "
                        "(run_id, destination_alias, status, attempts, available_at) "
                        "VALUES (:run_id, 'other_alias', 'pending', 0, :now)"
                    ),
                    {"run_id": run_id, "now": now},
                )
            connection.rollback()

        from datetime import UTC, datetime

        from sqlalchemy.orm import Session

        with Session(control_engine) as session:
            repository = DataCycleNotificationOutboxRepository(session)
            first_attempt = datetime(2026, 9, 27, 8, tzinfo=UTC)
            claimed = repository.claim_due(at=first_attempt)
            item = next(item for item in claimed if item.run_id == run_id)
            assert item.lease_token is not None
            session.commit()

            assert repository.retry(
                item.id,
                item.lease_token,
                error_code="telegram_send_failed",
                at=first_attempt,
            )
            session.commit()

            retried = repository.claim_due(at=datetime(2026, 9, 27, 8, 0, 30, tzinfo=UTC))
            item = next(item for item in retried if item.run_id == run_id)
            assert item.attempts == 2
            assert item.lease_token is not None
            assert repository.acknowledge(
                item.id,
                item.lease_token,
                at=datetime(2026, 9, 27, 8, 0, 30, tzinfo=UTC),
            )
            session.commit()

        with reader_engine.connect() as connection, pytest.raises(SQLAlchemyError):
            connection.execute(
                text("SELECT count(*) FROM data_cycle_notification_outbox")
            ).scalar_one()
    finally:
        control_engine.dispose()
        reader_engine.dispose()
        worker_engine.dispose()
