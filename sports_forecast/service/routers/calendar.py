"""Публичное API source-календаря независимо от прогнозной витрины."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.repository import CalendarRepository
from sports_forecast.service.event_readiness import evaluate_event_readiness
from sports_forecast.service.readiness_policy import load_readiness_policy
from sports_forecast.service.schemas import (
    CalendarCoverageResponse,
    CalendarEventResponse,
    CalendarResponse,
)
from sports_forecast.utils.bookmaker_calendar import bookmaker_window


router = APIRouter(prefix="/calendar", tags=["calendar"])
CalendarPeriod = Literal["today", "tomorrow", "3", "7", "14", "30"]
COVERAGE_FRESHNESS = timedelta(hours=24)


def _as_utc(value: datetime) -> datetime:
    """Сериализовать DB datetime wall time как UTC по service-store convention."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utc_now() -> datetime:
    """Вернуть текущее время UTC (отдельная граница для детерминированного теста)."""
    return datetime.now(UTC)


def calendar_window(now: datetime, period: CalendarPeriod) -> tuple[datetime, datetime]:
    """Вычислить полуоткрытое окно московских букмекерских суток от 08:00."""
    if now.tzinfo is None:
        raise ValueError("Момент календарного окна должен содержать часовой пояс")
    if period == "tomorrow":
        start, end = bookmaker_window(now, 1)
        return start + timedelta(days=1), end + timedelta(days=1)
    start, end = bookmaker_window(now, 1 if period == "today" else int(period))
    return max(start, now.astimezone(UTC)), end


@router.get("/{tournament}", response_model=CalendarResponse)
def get_calendar(
    tournament: str,
    period: Annotated[CalendarPeriod, Query()] = "today",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CalendarResponse:
    """Получить source events в выбранных букмекерских сутках."""
    now = utc_now()
    start_at, end_at = calendar_window(now, period)
    with get_session() as session:
        repository = CalendarRepository(session)
        events, total = repository.list_events(
            tournament=tournament,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
        coverage = repository.get_coverage(
            tournament=tournament,
        )
        predictions_by_event, odds_by_event = repository.get_readiness_data(events)
        event_readiness = {
            event.id: evaluate_event_readiness(
                event,
                predictions_by_event[event.id],
                odds_by_event[event.id],
                load_readiness_policy(event.tournament),
                now,
            )
            for event in events
        }

    is_covered = bool(
        coverage
        and coverage.complete
        and _as_utc(coverage.covered_from) <= start_at
        and _as_utc(coverage.covered_until) >= end_at
    )
    is_stale = bool(coverage and utc_now() - _as_utc(coverage.checked_at) > COVERAGE_FRESHNESS)
    if coverage is None:
        coverage_status = "unknown"
    elif coverage.failure_code:
        coverage_status = "unavailable"
    elif is_stale:
        coverage_status = "stale"
    elif not is_covered:
        coverage_status = "incomplete"
    elif total == 0:
        coverage_status = "confirmed_empty"
    else:
        coverage_status = "complete"

    return CalendarResponse(
        tournament=tournament,
        period=period,
        start_at=start_at,
        end_at=end_at,
        total=total,
        limit=limit,
        offset=offset,
        coverage=CalendarCoverageResponse(
            status=coverage_status,
            covered_from=_as_utc(coverage.covered_from) if coverage else None,
            covered_until=_as_utc(coverage.covered_until) if coverage else None,
            checked_at=_as_utc(coverage.checked_at) if coverage else None,
        ),
        events=[
            CalendarEventResponse(
                event_id=str(event.id),
                tournament=event.tournament,
                scheduled_at=_as_utc(event.scheduled_at),
                status=event.status,
                home_participant=event.home_participant,
                away_participant=event.away_participant,
                calendar_updated_at=_as_utc(event.last_ingested_at),
                **event_readiness[event.id],
            )
            for event in events
        ],
    )
