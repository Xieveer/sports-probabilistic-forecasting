"""Лёгкий tournament-neutral poll live коэффициентов и delta-доставка."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sports_forecast.orchestration.initial_notification import NotificationDeliveryError
from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import (
    NotificationPlan,
    NotificationStateService,
    QuoteSnapshot,
)
from sports_forecast.orchestration.telegram_http import telegram_send_message
from sports_forecast.service.db.repository import NotificationStateRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class OddsPollError(RuntimeError):
    """Неуспех batch-получения линий либо их пользовательской доставки."""


class PredictionInput(Protocol):
    """Минимальный тип materialized предсказания для batch adapter-а."""


QuoteFetcher = Callable[[Sequence[PredictionInput]], Sequence[QuoteSnapshot]]


@dataclass(frozen=True)
class OddsPollResult:
    """Наблюдаемый итог одного лёгкого цикла."""

    status: Literal["no_relevant_matches", "no_change", "notification_created"]
    recipient_count: int = 0


def run_odds_poll(
    *,
    profile: NotificationProfile,
    now: datetime,
    predictions: Sequence[PredictionInput],
    fetch_quotes: QuoteFetcher,
    allowed_chat_ids: tuple[str, ...],
    token: str,
    state_repository: NotificationStateRepository,
    logical_cycle: str | None = None,
) -> OddsPollResult:
    """Получить линии одним batch-вызовом и разослать одну aggregate delta.

    Adapter вызывается только при наличии materialized предсказаний в окне профиля.
    Повтор одного ``logical_cycle`` использует delivery ledger и не повторяет уже
    подтверждённые Telegram-доставки.
    """
    if not predictions:
        return OddsPollResult(status="no_relevant_matches")

    try:
        snapshots = list(fetch_quotes(predictions))
    except Exception as exc:
        logger.warning("Не удалось получить live коэффициенты profile=%s", profile.profile_id)
        raise OddsPollError("Не удалось получить live коэффициенты") from exc

    plan = NotificationStateService(state_repository).plan_poll(
        profile_id=profile.profile_id,
        logical_cycle=logical_cycle or now.isoformat(),
        snapshots=snapshots,
        now=now,
    )
    if plan.status != "notification_created":
        return OddsPollResult(status=plan.status)

    if not token.strip():
        raise OddsPollError("Токен Telegram не настроен")
    recipients = tuple(chat_id.strip() for chat_id in allowed_chat_ids if chat_id.strip())
    if not recipients:
        raise OddsPollError("Список получателей Telegram пуст")
    if plan.cycle_id is None:
        raise OddsPollError("Не создано состояние цикла коэффициентов")

    text = _build_delta_digest(plan)
    delivered = 0
    for chat_id in recipients:
        delivery = state_repository.reserve_delivery(plan.cycle_id, chat_id)
        if delivery is None:
            continue
        try:
            response = telegram_send_message(token=token, chat_id=chat_id, text=text)
            if not response.get("ok"):
                raise NotificationDeliveryError("Telegram отклонил delta-digest")
        except Exception as exc:
            state_repository.mark_delivery_failed(delivery)
            logger.warning("Не удалось доставить delta-digest chat_id=%s", _mask_chat_id(chat_id))
            raise OddsPollError("Не удалось доставить обновление коэффициентов") from exc
        state_repository.mark_delivery_sent(delivery)
        delivered += 1
    return OddsPollResult(status="notification_created", recipient_count=delivered)


def _build_delta_digest(plan: NotificationPlan) -> str:
    """Собрать один компактный текст всех изменений текущего цикла."""
    lines = ["Обновление коэффициентов"]
    for change in plan.changes:
        kind = "Новые" if change.kind == "new" else "Изменены"
        prices = ", ".join(f"{side}: {price:g}" for side, price in sorted(change.line.items()))
        lines.append(f"{kind} · {change.match_id}: {prices}")
    text = "\n".join(lines)
    if len(text) <= 4090:
        return text
    return f"{text[:4050]}\n… Обновление усечено."


def _mask_chat_id(chat_id: str) -> str:
    """Скрыть Telegram chat ID в журнале, сохранив возможность корреляции."""
    return f"***{chat_id[-4:]}" if len(chat_id) > 4 else "***"


__all__ = ["OddsPollError", "OddsPollResult", "PredictionInput", "QuoteFetcher", "run_odds_poll"]
