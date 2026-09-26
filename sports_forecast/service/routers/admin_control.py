"""Закрытый API управления schedule и запросами Data Cycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from sports_forecast.service.control_auth import require_control_admin
from sports_forecast.service.data_cycle_control import (
    SUPPORTED_PIPELINES,
    ScheduleRevisionConflictError,
    get_or_create_schedule,
    request_manual_run,
    update_schedule,
)
from sports_forecast.service.data_cycle_history import (
    get_current_run,
    list_recent_runs,
    serialize_run,
)
from sports_forecast.service.db.engine import get_control_session
from sports_forecast.service.db.models import DataCycleDispatcherState
from sports_forecast.service.db.repository import DataCycleRunRepository


router = APIRouter(prefix="/admin", tags=["admin-control"])
DISPATCHER_HEARTBEAT_TTL = timedelta(minutes=3)


class ScheduleUpdate(BaseModel):
    """Полный optimistic update persistent schedule."""

    expected_revision: int = Field(ge=1)
    enabled: bool
    base_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=64)
    interval_hours: int


def _pipeline(pipeline_id: str) -> None:
    if pipeline_id not in SUPPORTED_PIPELINES:
        raise HTTPException(status_code=404, detail="Pipeline не найден")


def _schedule_dto(schedule: Any, heartbeat_at: datetime | None, now: datetime) -> dict[str, Any]:
    heartbeat = (
        heartbeat_at.replace(tzinfo=UTC)
        if heartbeat_at and heartbeat_at.tzinfo is None
        else heartbeat_at
    )
    return {
        "pipeline_id": schedule.pipeline_id,
        "enabled": schedule.enabled,
        "base_time": schedule.base_time,
        "timezone": schedule.timezone,
        "interval_hours": schedule.interval_hours,
        "revision": schedule.revision,
        "next_run_at": schedule.next_run_at,
        "last_run_at": schedule.last_run_at,
        "last_missed_slots": schedule.last_missed_slots,
        "dispatcher_heartbeat_at": heartbeat,
        "dispatcher_healthy": bool(heartbeat and now - heartbeat <= DISPATCHER_HEARTBEAT_TTL),
    }


def _current_dispatcher_heartbeat(session) -> datetime | None:
    row = session.scalar(
        select(DataCycleDispatcherState)
        .order_by(desc(DataCycleDispatcherState.heartbeat_at))
        .limit(1)
    )
    return cast(datetime, row.heartbeat_at) if row else None


def _read_schedule(session, pipeline_id: str, now: datetime) -> dict[str, Any]:
    schedule = get_or_create_schedule(session, pipeline_id, now=now)
    return _schedule_dto(schedule, _current_dispatcher_heartbeat(session), now)


@router.get("/pipelines")
def list_pipelines(
    _admin: Annotated[str, Depends(require_control_admin)],
) -> dict[str, Any]:
    """Получить доступные pipeline и текущее cycle state."""
    now = datetime.now(UTC)
    with get_control_session() as session:
        pipelines = []
        for pipeline_id in sorted(SUPPORTED_PIPELINES):
            schedule = _read_schedule(session, pipeline_id, now)
            schedule["current_run"] = get_current_run(session, pipeline_id)
            recent = list_recent_runs(session, pipeline_id, limit=1)
            schedule["last_run"] = recent[0] if recent else None
            pipelines.append(schedule)
    return {"pipelines": pipelines}


@router.get("/pipelines/{pipeline_id}/schedule")
def get_schedule(
    pipeline_id: str,
    _admin: Annotated[str, Depends(require_control_admin)],
) -> dict[str, Any]:
    """Получить persistent schedule, вычисленное время и состояние dispatcher."""
    _pipeline(pipeline_id)
    now = datetime.now(UTC)
    with get_control_session() as session:
        return _read_schedule(session, pipeline_id, now)


@router.patch("/pipelines/{pipeline_id}/schedule")
def patch_schedule(
    pipeline_id: str,
    body: ScheduleUpdate,
    _admin: Annotated[str, Depends(require_control_admin)],
) -> dict[str, Any]:
    """Изменить schedule с optimistic revision check."""
    _pipeline(pipeline_id)
    now = datetime.now(UTC)
    try:
        with get_control_session() as session:
            schedule = update_schedule(
                session,
                pipeline_id,
                expected_revision=body.expected_revision,
                enabled=body.enabled,
                base_time=body.base_time,
                timezone=body.timezone,
                interval_hours=body.interval_hours,
                now=now,
            )
            return _schedule_dto(schedule, _current_dispatcher_heartbeat(session), now)
    except ScheduleRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail="Расписание уже изменено") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/pipelines/{pipeline_id}/runs", status_code=202)
def create_manual_run(
    pipeline_id: str,
    _admin: Annotated[str, Depends(require_control_admin)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Принять один ручной запуск или вернуть уже активный run."""
    _pipeline(pipeline_id)
    if idempotency_key is None or not 1 <= len(idempotency_key) <= 192:
        raise HTTPException(status_code=400, detail="Требуется Idempotency-Key")
    now = datetime.now(UTC)
    try:
        with get_control_session() as session:
            run, created = request_manual_run(session, pipeline_id, idempotency_key, now=now)
            response = serialize_run(run)
            response["created"] = created
            response["active_run"] = run.status in {"waiting", "running"}
            return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный запрос") from exc


@router.get("/pipelines/{pipeline_id}/runs")
def get_runs(
    pipeline_id: str,
    _admin: Annotated[str, Depends(require_control_admin)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    """Получить текущий и ограниченный список предыдущих Data Cycle."""
    _pipeline(pipeline_id)
    with get_control_session() as session:
        return {
            "current": get_current_run(session, pipeline_id),
            "runs": list_recent_runs(session, pipeline_id, limit=limit),
        }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    _admin: Annotated[str, Depends(require_control_admin)],
) -> dict[str, Any]:
    """Получить безопасный DTO одного Data Cycle run."""
    with get_control_session() as session:
        run = DataCycleRunRepository(session).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run не найден")
        return serialize_run(run)
