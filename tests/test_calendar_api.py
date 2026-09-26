"""Контракт календарного API независимо от prediction-витрины."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.service.app import app
from sports_forecast.service.db.models import (
    Base,
    CalendarCoverage,
    CanonicalEvent,
    CanonicalEventRevision,
)
from sports_forecast.service.routers import calendar
from sports_forecast.utils.bookmaker_calendar import bookmaker_window


def test_bookmaker_calendar_windows_follow_moscow_0800_boundary() -> None:
    """Окно 30 суток включает остаток текущего bookmaker day с точной границей."""
    before_0800 = datetime(2026, 9, 26, 0, tzinfo=UTC)  # 03:00 МСК
    start, end = bookmaker_window(before_0800, 30)
    assert start == datetime(2026, 9, 25, 5, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 5, tzinfo=UTC)

    at_0800 = datetime(2026, 9, 26, 5, tzinfo=UTC)
    start_at_boundary, end_at_boundary = bookmaker_window(at_0800, 1)
    assert start_at_boundary == at_0800
    assert end_at_boundary == datetime(2026, 9, 27, 5, tzinfo=UTC)


def test_calendar_today_excludes_events_before_current_time() -> None:
    """Текущий день отдаёт только матчи, которые ещё не начались."""
    start, end = calendar.calendar_window(datetime(2026, 9, 26, 0, tzinfo=UTC), "today")
    assert start == datetime(2026, 9, 26, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 26, 5, tzinfo=UTC)


def test_calendar_tomorrow_is_next_full_bookmaker_day() -> None:
    """Завтра остаётся полными сутками и до, и после границы 08:00 МСК."""
    before_boundary = calendar.calendar_window(datetime(2026, 9, 26, 0, tzinfo=UTC), "tomorrow")
    after_boundary = calendar.calendar_window(datetime(2026, 9, 26, 6, tzinfo=UTC), "tomorrow")
    assert before_boundary == (
        datetime(2026, 9, 26, 5, tzinfo=UTC),
        datetime(2026, 9, 27, 5, tzinfo=UTC),
    )
    assert after_boundary == (
        datetime(2026, 9, 27, 5, tzinfo=UTC),
        datetime(2026, 9, 28, 5, tzinfo=UTC),
    )


def test_calendar_returns_canonical_event_without_prediction(monkeypatch) -> None:
    """Календарь показывает source event без связанной prediction-записи."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    event = CanonicalEvent(
        sport="ice_hockey",
        tournament="nhl",
        source="nhl_web_api",
        source_event_id="2026020001",
        scheduled_at=datetime(2026, 9, 26, 1, tzinfo=UTC),
        status="scheduled",
        current_revision_sha256="a" * 64,
        home_participant="NYR",
        away_participant="PIT",
    )
    session.add(event)
    session.flush()
    session.add(
        CanonicalEventRevision(
            canonical_event_id=event.id,
            revision_sha256="a" * 64,
            payload_json='{"home_team":"NYR","away_team":"PIT"}',
            result_json="{}",
            source_observed_at=datetime(2026, 9, 25, tzinfo=UTC),
        )
    )
    session.commit()
    expected_event_id = str(event.id)

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    try:
        response = TestClient(app).get(
            "/calendar/nhl",
            params={"period": "today"},
        )
    finally:
        session.close()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["event_id"] == expected_event_id
    assert payload["events"][0]["home_participant"] == "NYR"
    assert payload["events"][0]["status"] == "scheduled"
    assert payload["coverage"]["status"] == "unknown"


def test_calendar_distinguishes_confirmed_empty_period_from_unknown(monkeypatch) -> None:
    """Полное coverage с нулём событий возвращается как подтверждённо пустой период."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            CalendarCoverage(
                tournament="nhl",
                source="nhl_web_api",
                covered_from=datetime(2026, 9, 25, 0),
                covered_until=datetime(2026, 10, 27, 0),
                complete=True,
                checked_at=datetime(2026, 9, 25, 12),
            )
        )
        session.commit()

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    try:
        response = TestClient(app).get("/calendar/nhl", params={"period": "today"})
    finally:
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["total"] == 0
    assert payload["coverage"]["status"] == "confirmed_empty"


def test_calendar_paginates_generic_tournament_events(monkeypatch) -> None:
    """Общий контракт календаря принимает иной sport/source и сохраняет pagination."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        expected_event_ids = []
        for event_id, scheduled_at in (
            ("soccer-feed:fixture-A", datetime(2026, 9, 26, 1)),
            ("soccer-feed:fixture-B", datetime(2026, 9, 26, 2)),
        ):
            event = CanonicalEvent(
                sport="football",
                tournament="epl",
                source="soccer_feed",
                source_event_id=event_id,
                scheduled_at=scheduled_at,
                status="scheduled",
                current_revision_sha256="b" * 64,
                home_participant="ARS",
                away_participant="CHE",
            )
            session.add(event)
            expected_event_ids.append(event)
        session.add(
            CalendarCoverage(
                tournament="epl",
                source="soccer_feed",
                covered_from=datetime(2026, 9, 25),
                covered_until=datetime(2026, 10, 27),
                complete=True,
                checked_at=datetime(2026, 9, 25, 12),
            )
        )
        session.commit()
        expected_second_id = str(expected_event_ids[1].id)

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    try:
        client = TestClient(app)
        response = client.get("/calendar/epl", params={"period": "3", "limit": 1, "offset": 1})
        empty_page = client.get("/calendar/epl", params={"period": "3", "limit": 1, "offset": 2})
    finally:
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [event["event_id"] for event in payload["events"]] == [expected_second_id]
    assert payload["coverage"]["status"] == "complete"
    assert empty_page.json()["events"] == []
    assert empty_page.json()["total"] == 2
    # Пустая страница из-за offset — период календаря не является пустым.
    assert empty_page.json()["coverage"]["status"] == "complete"


def test_calendar_excludes_confirmed_started_and_finished_events(monkeypatch) -> None:
    """Статусы started/finished исключаются из future выдачи даже при будущем времени."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for event_id, status in (("ready", "scheduled"), ("live", "started"), ("done", "finished")):
            session.add(
                CanonicalEvent(
                    sport="ice_hockey",
                    tournament="nhl",
                    source="nhl_web_api",
                    source_event_id=event_id,
                    scheduled_at=datetime(2026, 9, 26, 1),
                    status=status,
                    current_revision_sha256="c" * 64,
                    home_participant="NYR",
                    away_participant="PIT",
                )
            )
        session.commit()

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    try:
        response = TestClient(app).get("/calendar/nhl", params={"period": "today"})
    finally:
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [event["status"] for event in response.json()["events"]] == ["scheduled"]


def test_calendar_coverage_reports_incomplete_and_stale(monkeypatch) -> None:
    """Неполная попытка и просроченная проверка не выдаются за актуальный календарь."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        coverage = CalendarCoverage(
            tournament="nhl",
            source="nhl_web_api",
            covered_from=datetime(2026, 9, 25),
            covered_until=datetime(2026, 10, 27),
            complete=False,
            checked_at=datetime(2026, 9, 26),
        )
        session.add(coverage)
        session.commit()
        coverage_id = coverage.id

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    client = TestClient(app)
    try:
        incomplete = client.get("/calendar/nhl", params={"period": "today"})
        assert incomplete.json()["coverage"]["status"] == "incomplete"

        with Session(engine) as session:
            coverage = session.get(CalendarCoverage, coverage_id)
            assert coverage is not None
            coverage.complete = True
            coverage.checked_at = datetime(2026, 9, 24, 23, 59)
            session.commit()

        stale = client.get("/calendar/nhl", params={"period": "today"})
    finally:
        engine.dispose()

    assert stale.status_code == 200
    assert stale.json()["coverage"]["status"] == "stale"
