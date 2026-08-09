"""Контрактные и DB-тесты состояния уведомлений."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect

from sports_forecast.orchestration.notification_state import (
    NotificationStateService,
    QuoteSnapshot,
)
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import NotificationStateRepository


@pytest.fixture
def state_repository():
    """Создаёт чистую SQLite-схему состояния уведомлений."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    with get_session(engine=engine) as session:
        yield NotificationStateRepository(session)
    engine.dispose()
    reset_engine()


def _quote(
    match_id: str,
    starts_at: datetime,
    line: dict[str, float] | None,
) -> QuoteSnapshot:
    return QuoteSnapshot(match_id=match_id, starts_at=starts_at, line=line)


def test_poll_distinguishes_new_changed_and_absent_lines(state_repository) -> None:
    """Poll создаёт delta только для новой или изменённой валидной линии."""
    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    service = NotificationStateService(state_repository)
    starts_at = now + timedelta(hours=2)

    service.record_baseline(
        profile_id="hockey-main",
        snapshots=[_quote("known", starts_at, {"home": 1.9, "away": 2.1})],
        now=now,
    )

    result = service.plan_poll(
        profile_id="hockey-main",
        logical_cycle="2026-08-07T09:15:00Z",
        snapshots=[
            _quote("known", starts_at, {"home": 2.0, "away": 1.95}),
            _quote("new", starts_at, {"home": 1.8, "away": 2.2}),
            _quote("missing", starts_at, None),
        ],
        now=now,
    )

    assert result.status == "notification_created"
    assert [(change.match_id, change.kind) for change in result.changes] == [
        ("known", "changed"),
        ("new", "new"),
    ]

    unchanged = service.plan_poll(
        profile_id="hockey-main",
        logical_cycle="2026-08-07T09:30:00Z",
        snapshots=[
            _quote("known", starts_at, {"away": 1.95, "home": 2.0}),
            _quote("new", starts_at, {"home": 1.8, "away": 2.2}),
            _quote("missing", starts_at, None),
        ],
        now=now,
    )
    assert unchanged.status == "no_change"


def test_started_matches_do_not_create_delta_or_keep_poll_active(state_repository) -> None:
    """Матч на границе начала и после неё исключается из poll."""
    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    service = NotificationStateService(state_repository)

    result = service.plan_poll(
        profile_id="hockey-main",
        logical_cycle="2026-08-07T09:15:00Z",
        snapshots=[
            _quote("started", now, {"home": 1.8, "away": 2.2}),
            _quote("past", now - timedelta(seconds=1), {"home": 1.7, "away": 2.3}),
        ],
        now=now,
    )

    assert result.status == "no_relevant_matches"
    assert result.changes == ()


@pytest.mark.parametrize(
    "line",
    [
        {"home": 1.0, "away": 2.2},
        {"home": 0.0, "away": 2.2},
        {"home": -1.8, "away": 2.2},
    ],
)
def test_poll_ignores_non_decimal_quote_values(state_repository, line: dict[str, float]) -> None:
    """Линия допустима только при decimal-значениях строго больше единицы."""
    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)

    result = NotificationStateService(state_repository).plan_poll(
        profile_id="hockey-main",
        logical_cycle="2026-08-07T09:15:00Z",
        snapshots=[_quote("match-1", now + timedelta(hours=2), line)],
        now=now,
    )

    assert result.status == "no_change"


def test_delivery_ledger_deduplicates_success_and_retries_unsent_recipient(
    state_repository,
) -> None:
    """Успешная доставка не дублируется, а pending-получатель доступен для retry."""
    now = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    service = NotificationStateService(state_repository)
    starts_at = now + timedelta(hours=2)
    cycle = "2026-08-07T09:15:00Z"

    planned = service.plan_poll(
        profile_id="hockey-main",
        logical_cycle=cycle,
        snapshots=[_quote("new", starts_at, {"home": 1.8, "away": 2.2})],
        now=now,
    )
    assert planned.status == "notification_created"
    assert planned.cycle_id is not None

    first = state_repository.reserve_delivery(planned.cycle_id, chat_id="101")
    assert first is not None
    state_repository.mark_delivery_sent(first)
    assert state_repository.reserve_delivery(planned.cycle_id, chat_id="101") is None

    pending = state_repository.reserve_delivery(planned.cycle_id, chat_id="202")
    assert pending is not None
    state_repository.mark_delivery_failed(pending)
    retry = state_repository.reserve_delivery(planned.cycle_id, chat_id="202")
    assert retry is not None
    assert retry.id == pending.id
    assert retry.attempts == 2


def test_notification_schema_is_additive_to_predictions() -> None:
    """Новые таблицы создаются в чистой БД, не меняя таблицу predictions."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)

    inspector = inspect(engine)
    assert {"notification_line_states", "notification_cycles", "notification_deliveries"} <= set(
        inspector.get_table_names()
    )
    assert "match_id" in {column["name"] for column in inspector.get_columns("predictions")}
    engine.dispose()
