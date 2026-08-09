"""DB-first и идемпотентность confirmed-lineup fast path."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from typing import TypedDict

from sqlalchemy import create_engine

from sports_forecast.orchestration.lineup_fast_path import (
    deliver_pending_lineup_notifications,
    process_confirmed_lineup,
)
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import LineupFastPathRepository


class ConfirmedLineupArgs(TypedDict):
    """Аргументы записи confirmed lineup для проверки контракта репозитория."""

    match_id: str
    tournament: str
    model_pool: str
    immutable_model_version: str
    lineup_source: str
    lineup_received_at: datetime
    lineup_fingerprint: str
    prediction_json: str


def test_confirmed_lineup_is_saved_once_with_pending_delivery() -> None:
    """Повтор confirmed event не создаёт новую revision или outbox delivery."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            repo = LineupFastPathRepository(session)
            args: ConfirmedLineupArgs = {
                "match_id": "match-1",
                "tournament": "football_nationals",
                "model_pool": "football_nationals_winner",
                "immutable_model_version": "pool:football_nationals_winner:winner:abc",
                "lineup_source": "fixture",
                "lineup_received_at": datetime(2026, 8, 9, tzinfo=UTC),
                "lineup_fingerprint": "confirmed:match-1:abc",
                "prediction_json": '{"home_win":0.6}',
            }

            first, created = repo.record_confirmed_lineup(**args)
            second, repeated_created = repo.record_confirmed_lineup(**args)

            assert created is True
            assert repeated_created is False
            assert second.id == first.id
            assert repo.pending_delivery_count() == 1
    finally:
        engine.dispose()
        reset_engine()


def test_failed_delivery_is_retried_without_creating_another_revision() -> None:
    """Telegram сбой оставляет outbox для retry без повторного расчёта прогнозов."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            repo = LineupFastPathRepository(session)
            repo.record_confirmed_lineup(
                match_id="match-1",
                tournament="football_nationals",
                model_pool="football_nationals_winner",
                immutable_model_version="pool:football_nationals_winner:winner:abc",
                lineup_source="fixture",
                lineup_received_at=datetime(2026, 8, 9, tzinfo=UTC),
                lineup_fingerprint="confirmed:match-1:abc",
                prediction_json='{"home_win":0.6}',
            )

            assert (
                deliver_pending_lineup_notifications(
                    repo, lambda _: (_ for _ in ()).throw(OSError())
                )
                == 0
            )
            assert repo.pending_delivery_count() == 1
            assert deliver_pending_lineup_notifications(repo, lambda _: None) == 1
            assert repo.pending_delivery_count() == 0
    finally:
        engine.dispose()
        reset_engine()


def test_incomplete_lineup_does_not_start_single_match_inference() -> None:
    """Неполный confirmed состав не создаёт revision и не вызывает inference."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            repo = LineupFastPathRepository(session)
            called = False

            def infer() -> str:
                nonlocal called
                called = True
                return '{"home_win":0.6}'

            created = process_confirmed_lineup(
                repo,
                match_id="match-1",
                tournament="football_nationals",
                model_pool="football_nationals_winner",
                immutable_model_version="pool:football_nationals_winner:winner:abc",
                lineup_source="fixture",
                lineup_received_at=datetime(2026, 8, 9, tzinfo=UTC),
                lineup_fingerprint="confirmed:match-1:incomplete",
                lineup_complete=False,
                infer=infer,
            )

            assert created is False
            assert called is False
            assert repo.pending_delivery_count() == 0
    finally:
        engine.dispose()
        reset_engine()


def test_local_confirmed_lineup_path_completes_within_one_minute() -> None:
    """Локальный adapter DB-first → outbox выполняет контракт минутного fast path."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            repo = LineupFastPathRepository(session)
            started = monotonic()
            assert process_confirmed_lineup(
                repo,
                match_id="match-latency",
                tournament="football_nationals",
                model_pool="football_nationals_winner",
                immutable_model_version="pool:football_nationals_winner:winner:abc",
                lineup_source="fixture",
                lineup_received_at=datetime(2026, 8, 9, tzinfo=UTC),
                lineup_fingerprint="confirmed:match-latency:abc",
                lineup_complete=True,
                infer=lambda: '{"home_win":0.6}',
            )
            assert deliver_pending_lineup_notifications(repo, lambda _: None) == 1
            assert monotonic() - started < 60
    finally:
        engine.dispose()
        reset_engine()
