"""Контракты транзакционного per-tournament refresh lock."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import Base
from sports_forecast.service.db.refresh_lock import RefreshLockRepository


def test_tournament_lock_rejects_second_run_until_owner_releases() -> None:
    """Один tournament не выполняется параллельно разными scheduler run."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        locks = RefreshLockRepository(session)
        assert locks.acquire(tournament="nhl", run_id="run-1") is True
        assert locks.acquire(tournament="nhl", run_id="run-2") is False
        locks.release(tournament="nhl", run_id="run-1")
        assert locks.acquire(tournament="nhl", run_id="run-2") is True
    finally:
        session.close()
