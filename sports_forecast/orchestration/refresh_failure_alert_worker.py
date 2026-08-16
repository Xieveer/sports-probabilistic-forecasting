"""Retry-доставка pending admin alerts после failed refresh."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.orchestration.initial_notification import notify_administrators
from sports_forecast.service.db.models import RefreshFailureAlert


def deliver_pending_refresh_failure_alerts(
    *, session: Session, admin_chat_ids: tuple[str, ...], token: str
) -> int:
    """Доставить pending alerts; неуспех оставляет запись доступной retry."""
    alerts = session.scalars(
        select(RefreshFailureAlert).where(RefreshFailureAlert.status == "pending")
    ).all()
    delivered = 0
    for alert in alerts:
        alert.attempts += 1
        try:
            notify_administrators(
                admin_chat_ids=admin_chat_ids, token=token, failure_kind=alert.failure_code
            )
        except Exception:
            continue
        alert.status = "sent"
        delivered += 1
    session.commit()
    return delivered
