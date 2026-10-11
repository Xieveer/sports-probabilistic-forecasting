"""Unit tests for ``PredictionRepository.get_upcoming_predictions`` (R37.2 time window)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import PredictionRepository
from sports_forecast.service.routers import calendar, predictions


def _upsert(
    repo: PredictionRepository,
    match_id: str,
    match_dt: datetime | None,
    *,
    tournament: str = "nhl",
    market: str = "winner",
    market_spec: str = "winner",
) -> None:
    repo.upsert_prediction(
        match_id=match_id,
        tournament=tournament,
        market=market,
        market_spec=market_spec,
        predictions={"home_win": 0.6, "away_win": 0.4},
        model_version="test",
        algorithm="dummy",
        featureset="basic",
        match_datetime=match_dt,
    )


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


@pytest.fixture
def memory_session():
    """In-memory SQLite session; таблицы ``predictions`` созданы через ``init_db``."""
    reset_engine()
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with get_session(engine=eng) as session:
        yield session
    eng.dispose()
    reset_engine()


def test_get_upcoming_predictions_respects_hours_window(memory_session) -> None:
    """Матчи вне [now, now+hours] и без match_datetime не попадают в выборку."""
    repo = PredictionRepository(memory_session)
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
    inside = now + timedelta(hours=10)
    outside = now + timedelta(hours=50)

    _upsert(repo, "in", _utc_naive(inside))
    _upsert(repo, "out", _utc_naive(outside))
    _upsert(repo, "nonull", None)
    memory_session.flush()

    rows = repo.get_upcoming_predictions(
        tournament="nhl",
        hours=48,
        now_utc=now,
    )
    assert [r.match_id for r in rows] == ["in"]


def test_get_upcoming_predictions_excludes_past_matches(memory_session) -> None:
    """Матчи строго до ``now_utc`` исключаются."""
    repo = PredictionRepository(memory_session)
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
    past = now - timedelta(hours=2)
    future = now + timedelta(hours=5)

    _upsert(repo, "past", _utc_naive(past))
    _upsert(repo, "future", _utc_naive(future))
    memory_session.flush()

    rows = repo.get_upcoming_predictions(tournament="nhl", hours=48, now_utc=now)
    assert [r.match_id for r in rows] == ["future"]


def test_get_upcoming_predictions_market_spec_filter(memory_session) -> None:
    """При заданном ``market_spec`` остаются только совпадающие строки."""
    repo = PredictionRepository(memory_session)
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
    t1 = now + timedelta(hours=1)

    _upsert(
        repo,
        "a",
        _utc_naive(t1),
        market="winner_withOT",
        market_spec="winner_withOT",
    )
    _upsert(repo, "b", _utc_naive(t1))
    memory_session.flush()

    ot_only = repo.get_upcoming_predictions(
        tournament="nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        hours=48,
        now_utc=now,
    )
    assert [r.match_id for r in ot_only] == ["a"]


def test_get_upcoming_predictions_uses_half_open_bookmaker_window(memory_session) -> None:
    """Явное окно включает начало и исключает границу следующих суток."""
    repo = PredictionRepository(memory_session)
    start = datetime(2026, 10, 11, 5, tzinfo=UTC)
    end = start + timedelta(days=1)
    for match_id, moment in (
        ("before", start - timedelta(seconds=1)),
        ("start", start),
        ("inside", end - timedelta(seconds=1)),
        ("end", end),
    ):
        _upsert(repo, match_id, _utc_naive(moment))
    memory_session.flush()

    rows = repo.get_upcoming_predictions(
        tournament="nhl",
        now_utc=start,
        window_start=start,
        window_end=end,
    )

    assert [row.match_id for row in rows] == ["start", "inside"]


def test_upcoming_api_today_passes_calendar_window(monkeypatch) -> None:
    """Период today использует ту же границу 08:00 МСК, что календарь."""
    now = datetime(2026, 10, 11, 4, tzinfo=UTC)
    seen: dict[str, object] = {}

    @contextmanager
    def fake_session():
        yield object()

    def fake_upcoming(self, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(calendar, "utc_now", lambda: now)
    monkeypatch.setattr(predictions, "get_session", fake_session)
    monkeypatch.setattr(PredictionRepository, "get_upcoming_predictions", fake_upcoming)

    result = predictions.get_upcoming(
        "nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        period="today",
        hours=48,
        live_pinnacle=False,
    )

    assert result.count == 0
    assert seen["window_start"] == now
    assert seen["window_end"] == datetime(2026, 10, 11, 5, tzinfo=UTC)
