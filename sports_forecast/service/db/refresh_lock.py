"""DB-backed per-tournament refresh lock."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import RefreshLock


class RefreshLockRepository:
    """Сериализует refresh одного турнира через unique DB row."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def acquire(self, *, tournament: str, run_id: str) -> bool:
        """Вернуть True только владельцу свободного tournament lock."""
        try:
            with self.session.begin_nested():
                self.session.add(RefreshLock(tournament=tournament, run_id=run_id))
                self.session.flush()
        except IntegrityError:
            return False
        return True

    def release(self, *, tournament: str, run_id: str) -> None:
        """Освободить lock только его текущему владельцу."""
        lock = (
            self.session.query(RefreshLock)
            .filter_by(tournament=tournament, run_id=run_id)
            .one_or_none()
        )
        if lock is not None:
            self.session.delete(lock)
            self.session.flush()
