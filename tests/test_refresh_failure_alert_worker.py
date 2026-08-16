"""Контракты retry-доставки refresh failure alert outbox."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.orchestration import refresh_failure_alert_worker
from sports_forecast.service.db.models import Base, RefreshFailureAlert


def test_failed_delivery_keeps_alert_pending_for_next_retry(monkeypatch) -> None:
    """Сбой Telegram не теряет alert и успешный retry не создаёт дубликат."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        alert = RefreshFailureAlert(
            run_id="run-1",
            tournament="nhl",
            failure_code="canonical_freshness_failed",
            status="pending",
        )
        session.add(alert)
        session.commit()

        def fail(**_kwargs: object) -> None:
            raise RuntimeError("network")

        monkeypatch.setattr(refresh_failure_alert_worker, "notify_administrators", fail)
        assert (
            refresh_failure_alert_worker.deliver_pending_refresh_failure_alerts(
                session=session, admin_chat_ids=("1",), token="x"
            )
            == 0
        )
        assert alert.status == "pending"
        assert alert.attempts == 1

        monkeypatch.setattr(
            refresh_failure_alert_worker, "notify_administrators", lambda **_kwargs: None
        )
        assert (
            refresh_failure_alert_worker.deliver_pending_refresh_failure_alerts(
                session=session, admin_chat_ids=("1",), token="x"
            )
            == 1
        )
        assert alert.status == "sent"
        assert alert.attempts == 2
    finally:
        session.close()
