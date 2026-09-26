"""Контракт бизнес-слотов persistent scheduler."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.orchestration.data_cycle_schedule import next_scheduled_at
from sports_forecast.service.data_cycle_control import (
    dispatch_due_run,
    request_manual_run,
    update_schedule,
)
from sports_forecast.service.db.models import (
    Base,
    DataCycleControlRequest,
    DataCycleRun,
    PipelineSchedule,
)
from sports_forecast.service.db.repository import DataCycleRunRepository


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 26, 6, 59, tzinfo=UTC), datetime(2026, 9, 26, 7, tzinfo=UTC)),
        (datetime(2026, 9, 26, 7, tzinfo=UTC), datetime(2026, 9, 26, 13, tzinfo=UTC)),
        (datetime(2026, 9, 26, 19, tzinfo=UTC), datetime(2026, 9, 27, 1, tzinfo=UTC)),
    ],
)
def test_next_slot_follows_base_time_with_daily_wrap(now, expected) -> None:
    assert next_scheduled_at("10:00", "Europe/Moscow", 6, now) == expected


@pytest.mark.parametrize(
    ("base_time", "timezone", "interval_hours"),
    [
        ("25:00", "Europe/Moscow", 6),
        ("10:00", "No/Such_Zone", 6),
        ("10:00", "Europe/Moscow", 5),
        ("10:00", "Europe/Moscow", 0),
    ],
)
def test_schedule_rejects_invalid_values(base_time, timezone, interval_hours) -> None:
    with pytest.raises(ValueError):
        next_scheduled_at(base_time, timezone, interval_hours, datetime.now(UTC))


def test_dispatcher_coalesces_missed_slots_and_does_not_queue_while_active() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            before_slot = datetime(2026, 9, 26, 6, 59, tzinfo=UTC)
            run, count = dispatch_due_run(session, "nhl", "host-test", now=before_slot)
            assert run is None
            assert count == 0
            update_schedule(
                session,
                "nhl",
                expected_revision=1,
                enabled=True,
                base_time="10:00",
                timezone="Europe/Moscow",
                interval_hours=6,
                now=before_slot,
            )

            late = datetime(2026, 9, 26, 20, 0, tzinfo=UTC)
            run, count = dispatch_due_run(session, "nhl", "host-test", now=late)
            assert run is not None
            assert run.reason == "scheduled"
            assert count == 3
            assert run.requested_at == datetime(2026, 9, 26, 20)
            assert run.scheduled_for == datetime(2026, 9, 26, 19)
            schedule = session.scalar(select(PipelineSchedule))
            assert schedule is not None
            assert schedule.last_missed_slots == 2
            assert schedule.next_run_at == datetime(2026, 9, 27, 1)

            next_due = datetime(2026, 9, 27, 1, tzinfo=UTC)
            pending, skipped_count = dispatch_due_run(session, "nhl", "host-test", now=next_due)
            assert pending is not None
            assert pending.run_id == run.run_id
            assert skipped_count == 1
            schedule = session.scalar(select(PipelineSchedule))
            assert schedule is not None
            assert schedule.last_missed_slots == 1
            assert schedule.next_run_at == datetime(2026, 9, 27, 7)
    finally:
        engine.dispose()


def test_dispatcher_delivers_manual_waiting_run_while_schedule_is_disabled() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            now = datetime(2026, 9, 26, 9, tzinfo=UTC)
            update_schedule(
                session,
                "nhl",
                expected_revision=1,
                enabled=False,
                base_time="10:00",
                timezone="Europe/Moscow",
                interval_hours=24,
                now=now,
            )
            run, created = request_manual_run(session, "nhl", "manual-test", now=now)
            assert created is True
            delivered, _ = dispatch_due_run(session, "nhl", "host-test", now=now)
            assert delivered is not None
            assert delivered.run_id == run.run_id
            assert delivered.reason == "manual"
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("SF_TEST_POSTGRES_URL"),
    reason="Задайте SF_TEST_POSTGRES_URL на disposable PostgreSQL для race tests",
)
def test_postgresql_serializes_due_dispatch_and_manual_idempotency() -> None:
    """PostgreSQL сериализует scheduled claim и одновременный manual retry."""
    engine = create_engine(os.environ["SF_TEST_POSTGRES_URL"], pool_size=5, max_overflow=0)
    schema = f"test_epic025_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped_engine)
        before = datetime(2026, 9, 26, 6, 59, tzinfo=UTC)
        due = datetime(2026, 9, 26, 7, 0, tzinfo=UTC)
        with Session(scoped_engine) as session:
            waiting, count = dispatch_due_run(session, "nhl", "pg-host", now=before)
            assert waiting is None and count == 0
            session.commit()

        start = Barrier(2)

        def dispatch() -> tuple[str | None, int]:
            with Session(scoped_engine, expire_on_commit=False) as session:
                start.wait(timeout=5)
                run, missed = dispatch_due_run(session, "nhl", "pg-host", now=due)
                session.commit()
                return (run.run_id if run is not None else None, missed)

        with ThreadPoolExecutor(max_workers=2) as executor:
            dispatch_results = list(executor.map(lambda _index: dispatch(), range(2)))
        run_ids = {run_id for run_id, _ in dispatch_results}
        assert len(run_ids) == 1 and None not in run_ids

        scheduled_run_id = next(iter(run_ids))
        with Session(scoped_engine) as session:
            DataCycleRunRepository(session).fail_run(
                scheduled_run_id, failure_code="executor_interrupted"
            )
            session.commit()

        manual_start = Barrier(2)

        def request_manual() -> str:
            with Session(scoped_engine, expire_on_commit=False) as session:
                manual_start.wait(timeout=5)
                run, _created = request_manual_run(
                    session,
                    "nhl",
                    "callback:single-update",
                    now=due,
                )
                session.commit()
                return run.run_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            manual_run_ids = list(executor.map(lambda _index: request_manual(), range(2)))
        assert manual_run_ids[0] == manual_run_ids[1]
        with Session(scoped_engine) as session:
            schedule = session.scalar(select(PipelineSchedule))
            assert schedule is not None and schedule.revision == 1

            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DataCycleRun)
                    .where(DataCycleRun.__table__.c.status.in_(("waiting", "running")))
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DataCycleControlRequest)
                    .where(DataCycleControlRequest.idempotency_key == "callback:single-update")
                )
                == 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
