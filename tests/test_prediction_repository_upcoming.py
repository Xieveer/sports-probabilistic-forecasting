"""Unit tests for ``PredictionRepository.get_upcoming_predictions`` (R37.2 time window)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import PredictionRepository


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
