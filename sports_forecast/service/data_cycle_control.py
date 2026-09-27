"""Транзакции schedule/manual control Data Cycle."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sports_forecast.orchestration.data_cycle_schedule import next_scheduled_at
from sports_forecast.service.db.models import (
    DataCycleControlRequest,
    DataCycleDispatcherState,
    DataCycleRun,
    PipelineSchedule,
)
from sports_forecast.service.db.repository import DataCycleRunRepository


SUPPORTED_PIPELINES = frozenset({"nhl"})
DEFAULT_ENABLED = True
DEFAULT_BASE_TIME = "10:00"
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_INTERVAL_HOURS = 24
EXECUTOR_STALE_AFTER = timedelta(minutes=95)


class ScheduleRevisionConflictError(Exception):
    """Изменение расписания основано на устаревшей revision."""


def utc_naive(value: datetime) -> datetime:
    """Преобразовать timezone-aware момент в БД UTC wall-time."""
    if value.tzinfo is None:
        raise ValueError("Текущее время должно содержать часовой пояс")
    return value.astimezone(UTC).replace(tzinfo=None)


def get_or_create_schedule(
    session: Session, pipeline_id: str, *, now: datetime
) -> PipelineSchedule:
    """Прочитать сохранённый schedule или атомарно создать исходное значение."""
    _validate_pipeline(pipeline_id)
    current = session.scalar(
        select(PipelineSchedule).where(PipelineSchedule.pipeline_id == pipeline_id)
    )
    if current is not None:
        return cast(PipelineSchedule, current)
    now_db = utc_naive(now)
    row = PipelineSchedule(
        pipeline_id=pipeline_id,
        enabled=DEFAULT_ENABLED,
        base_time=DEFAULT_BASE_TIME,
        timezone=DEFAULT_TIMEZONE,
        interval_hours=DEFAULT_INTERVAL_HOURS,
        revision=1,
        next_run_at=utc_naive(
            next_scheduled_at(DEFAULT_BASE_TIME, DEFAULT_TIMEZONE, DEFAULT_INTERVAL_HOURS, now)
        ),
        updated_at=now_db,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
        return row
    except IntegrityError:
        current = session.scalar(
            select(PipelineSchedule).where(PipelineSchedule.pipeline_id == pipeline_id)
        )
        if current is None:
            raise
        return cast(PipelineSchedule, current)


def update_schedule(
    session: Session,
    pipeline_id: str,
    *,
    expected_revision: int,
    enabled: bool,
    base_time: str,
    timezone: str,
    interval_hours: int,
    now: datetime,
) -> PipelineSchedule:
    """Сохранить полную настройку schedule с optimistic revision."""
    from sports_forecast.orchestration.data_cycle_schedule import validate_schedule

    validate_schedule(base_time, timezone, interval_hours)
    row = get_or_create_schedule(session, pipeline_id, now=now)
    row = session.scalar(
        select(PipelineSchedule).where(PipelineSchedule.id == row.id).with_for_update()
    )
    if row is None or row.revision != expected_revision:
        raise ScheduleRevisionConflictError
    row.enabled = enabled
    row.base_time = base_time
    row.timezone = timezone
    row.interval_hours = interval_hours
    row.revision += 1
    row.updated_at = utc_naive(now)
    row.next_run_at = (
        utc_naive(next_scheduled_at(base_time, timezone, interval_hours, now)) if enabled else None
    )
    return row


def request_manual_run(
    session: Session, pipeline_id: str, idempotency_key: str, *, now: datetime
) -> tuple[DataCycleRun, bool, bool]:
    """Идемпотентно принять ручной запуск либо вернуть текущий active run."""
    _validate_pipeline(pipeline_id)
    if re.fullmatch(r"[A-Za-z0-9:_-]{1,192}", idempotency_key) is None:
        raise ValueError("Некорректный idempotency key")

    prior = session.scalar(
        select(DataCycleControlRequest).where(
            DataCycleControlRequest.idempotency_key == idempotency_key
        )
    )
    if prior is not None:
        run = DataCycleRunRepository(session).get(prior.run_id)
        if run is None:
            raise RuntimeError("Control request ссылается на отсутствующий run")
        return run, False, True

    repository = DataCycleRunRepository(session)
    active = repository.get_current(pipeline_id)
    try:
        with session.begin_nested():
            run = active or repository.create(
                run_id=str(uuid.uuid4()),
                tournament=pipeline_id,
                reason="manual",
                at=now,
            )
            session.add(
                DataCycleControlRequest(
                    idempotency_key=idempotency_key,
                    pipeline_id=pipeline_id,
                    run_id=run.run_id,
                )
            )
            session.flush()
        return run, active is None, False
    except IntegrityError:
        existing_request = session.scalar(
            select(DataCycleControlRequest).where(
                DataCycleControlRequest.idempotency_key == idempotency_key
            )
        )
        if existing_request is not None:
            run = repository.get(existing_request.run_id)
            if run is not None:
                return run, False, True
        active = repository.get_current(pipeline_id)
        if active is not None:
            return active, False, False
        raise


def heartbeat_dispatcher(session: Session, dispatcher_id: str, *, now: datetime) -> None:
    """Сохранить host dispatcher heartbeat без раскрытия host identity."""
    if not dispatcher_id or len(dispatcher_id) > 64:
        raise ValueError("Некорректный dispatcher ID")
    row = session.scalar(
        select(DataCycleDispatcherState).where(
            DataCycleDispatcherState.dispatcher_id == dispatcher_id
        )
    )
    if row is None:
        session.add(
            DataCycleDispatcherState(
                dispatcher_id=dispatcher_id,
                heartbeat_at=utc_naive(now),
            )
        )
    else:
        row.heartbeat_at = utc_naive(now)


def dispatch_due_run(
    session: Session,
    pipeline_id: str,
    dispatcher_id: str,
    *,
    now: datetime,
) -> tuple[DataCycleRun | None, int]:
    """Записать heartbeat и схлопнуть просроченные slots максимум в один run."""
    _validate_pipeline(pipeline_id)
    heartbeat_dispatcher(session, dispatcher_id, now=now)
    repository = DataCycleRunRepository(session)
    active = repository.get_current(pipeline_id)
    if active is not None and active.status == "running":
        repository.mark_executor_stalled(
            active.run_id,
            before=utc_naive(now - EXECUTOR_STALE_AFTER),
            at=now,
        )
        if active.executor_stalled_at is not None:
            return active, 0
    schedule = get_or_create_schedule(session, pipeline_id, now=now)
    schedule = session.scalar(
        select(PipelineSchedule).where(PipelineSchedule.id == schedule.id).with_for_update()
    )
    if schedule is None or not schedule.enabled or schedule.next_run_at is None:
        pending = session.scalar(
            select(DataCycleRun)
            .where(DataCycleRun.tournament == pipeline_id, DataCycleRun.status == "waiting")
            .order_by(DataCycleRun.requested_at, DataCycleRun.id)
            .limit(1)
        )
        return pending, 0

    now_db = utc_naive(now)
    next_slot = schedule.next_run_at
    if next_slot.tzinfo is None:
        next_slot = next_slot.replace(tzinfo=UTC)
    else:
        next_slot = next_slot.astimezone(UTC)
    if next_slot > now:
        pending = session.scalar(
            select(DataCycleRun)
            .where(DataCycleRun.tournament == pipeline_id, DataCycleRun.status == "waiting")
            .order_by(DataCycleRun.requested_at, DataCycleRun.id)
            .limit(1)
        )
        return pending, 0

    due_count = 0
    latest_due = next_slot
    interval = timedelta(hours=schedule.interval_hours)
    while next_slot <= now:
        latest_due = next_slot
        next_slot += interval
        due_count += 1
    schedule.next_run_at = utc_naive(
        next_scheduled_at(schedule.base_time, schedule.timezone, schedule.interval_hours, now)
    )
    schedule.last_run_at = now_db

    active = repository.get_current(pipeline_id)
    if active is not None:
        schedule.last_missed_slots = due_count
        return active if active.status == "waiting" else None, due_count

    idempotency_key = (
        f"scheduled:{pipeline_id}:{schedule.revision}:{latest_due.isoformat(timespec='seconds')}"
    )
    prior = session.scalar(
        select(DataCycleControlRequest).where(
            DataCycleControlRequest.idempotency_key == idempotency_key
        )
    )
    if prior is not None:
        schedule.last_missed_slots = due_count - 1
        return repository.get(prior.run_id), due_count

    run = repository.create(
        run_id=str(uuid.uuid4()),
        tournament=pipeline_id,
        reason="scheduled",
        scheduled_for=latest_due,
        at=now,
    )
    session.add(
        DataCycleControlRequest(
            idempotency_key=idempotency_key,
            pipeline_id=pipeline_id,
            run_id=run.run_id,
        )
    )
    schedule.last_missed_slots = due_count - 1
    return run, due_count


def _validate_pipeline(pipeline_id: str) -> None:
    if pipeline_id not in SUPPORTED_PIPELINES:
        raise ValueError("Неизвестный pipeline")
