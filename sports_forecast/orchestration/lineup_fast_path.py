"""Retry-доставка outbox confirmed-lineup без повторного inference."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sports_forecast.service.db.models import LineupNotificationOutbox
from sports_forecast.service.db.repository import LineupFastPathRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
DeliverySender = Callable[[LineupNotificationOutbox], None]


def deliver_pending_lineup_notifications(
    repository: LineupFastPathRepository, sender: DeliverySender
) -> int:
    """Доставить pending outbox; сбой сохраняет запись для следующего retry."""
    delivered = 0
    for delivery in repository.get_pending_deliveries():
        try:
            sender(delivery)
        except OSError:
            repository.record_delivery_failure(delivery)
            logger.warning("Не доставлено lineup notification id=%s", delivery.id)
            continue
        repository.mark_delivery_sent(delivery)
        delivered += 1
    return delivered


def process_confirmed_lineup(
    repository: LineupFastPathRepository,
    *,
    match_id: str,
    tournament: str,
    model_pool: str,
    immutable_model_version: str,
    lineup_source: str,
    lineup_received_at: datetime,
    lineup_fingerprint: str,
    lineup_complete: bool,
    infer: Callable[[], str],
) -> bool:
    """Выполнить single-match inference только для полного confirmed состава."""
    if not lineup_complete:
        logger.info("Lineup fast path пропущен: confirmed состав неполный match=%s", match_id)
        return False
    prediction_json = infer()
    revision, created = repository.record_confirmed_lineup(
        match_id=match_id,
        tournament=tournament,
        model_pool=model_pool,
        immutable_model_version=immutable_model_version,
        lineup_source=lineup_source,
        lineup_received_at=lineup_received_at,
        lineup_fingerprint=lineup_fingerprint,
        prediction_json=prediction_json,
    )
    logger.info("Lineup revision id=%s created=%s match=%s", revision.id, created, match_id)
    return created
