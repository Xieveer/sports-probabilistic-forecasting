"""Initial digest и безопасное уведомление администраторов."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sports_forecast.betting.live_moneyline_extras import proba_home_from_prediction
from sports_forecast.orchestration.digest_message import (
    DigestMatchLine,
    build_post_refresh_digest_text,
)
from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import (
    NotificationStateService,
    QuoteSnapshot,
)
from sports_forecast.orchestration.telegram_http import telegram_send_message
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import NotificationStateRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class NotificationDeliveryError(RuntimeError):
    """Неуспех Telegram-доставки без включения внешнего ответа в текст ошибки."""


@dataclass(frozen=True)
class InitialDigestResult:
    """Наблюдаемый результат initial digest."""

    status: Literal["notification_created"]
    recipient_count: int


def run_initial_digest(
    *,
    profile: NotificationProfile,
    now: datetime,
    predictions: list[Prediction],
    quote_snapshots: list[QuoteSnapshot],
    allowed_chat_ids: tuple[str, ...],
    token: str,
    state_repository: NotificationStateRepository,
) -> InitialDigestResult:
    """Отправить initial digest всем получателям и сохранить baseline линий."""
    if not token.strip():
        raise NotificationDeliveryError("Токен Telegram не настроен")
    recipients = tuple(chat_id.strip() for chat_id in allowed_chat_ids if chat_id.strip())
    if not recipients:
        raise NotificationDeliveryError("Список получателей Telegram пуст")

    state_service = NotificationStateService(state_repository)
    state_service.record_baseline(profile.profile_id, quote_snapshots, now)
    cycle = state_repository.get_cycle(profile.profile_id, _initial_logical_cycle(now))
    if cycle is None:
        cycle = state_repository.create_cycle(
            profile.profile_id,
            _initial_logical_cycle(now),
            "[]",
        )
    text = build_post_refresh_digest_text(
        matches=_match_lines(predictions, now=now, window_hours=profile.window_hours),
        provenance_line="—",
        odds_warning="none",
        header=f"Прогноз на ближайшие {profile.window_hours} часов",
    )
    delivered = 0
    for chat_id in recipients:
        delivery = state_repository.reserve_delivery(cycle.id, chat_id)
        if delivery is None:
            continue
        try:
            response = telegram_send_message(token=token, chat_id=chat_id, text=text)
        except Exception as exc:
            state_repository.mark_delivery_failed(delivery)
            logger.warning("Не удалось доставить initial digest chat_id=%s", _mask_chat_id(chat_id))
            raise NotificationDeliveryError("Не удалось доставить initial digest") from exc
        if not response.get("ok"):
            state_repository.mark_delivery_failed(delivery)
            logger.warning("Telegram отклонил initial digest chat_id=%s", _mask_chat_id(chat_id))
            raise NotificationDeliveryError("Telegram отклонил initial digest")
        state_repository.mark_delivery_sent(delivery)
        delivered += 1
    return InitialDigestResult(status="notification_created", recipient_count=delivered)


def notify_administrators(
    *,
    admin_chat_ids: tuple[str, ...],
    token: str,
    failure_kind: str,
) -> None:
    """Отправить администраторам краткое безопасное уведомление о неуспехе."""
    if not token.strip():
        raise NotificationDeliveryError("Токен Telegram не настроен")
    recipients = tuple(chat_id.strip() for chat_id in admin_chat_ids if chat_id.strip())
    if not recipients:
        raise NotificationDeliveryError("Список администраторов Telegram пуст")
    message = f"Сценарий уведомлений не завершён: {failure_kind}."
    failed = False
    for chat_id in recipients:
        try:
            response = telegram_send_message(token=token, chat_id=chat_id, text=message)
        except Exception:
            logger.warning("Не удалось уведомить администратора chat_id=%s", _mask_chat_id(chat_id))
            failed = True
            continue
        if not response.get("ok"):
            logger.warning("Telegram отклонил admin-уведомление chat_id=%s", _mask_chat_id(chat_id))
            failed = True
    if failed:
        raise NotificationDeliveryError("Не удалось уведомить всех администраторов")


def _mask_chat_id(chat_id: str) -> str:
    """Скрыть Telegram chat ID в журнале, сохранив возможность корреляции."""
    return f"***{chat_id[-4:]}" if len(chat_id) > 4 else "***"


def _initial_logical_cycle(now: datetime) -> str:
    """Вернуть устойчивый ключ daily initial digest в UTC."""
    current = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    return f"initial:{current.date().isoformat()}"


def _match_lines(
    predictions: list[Prediction],
    *,
    now: datetime,
    window_hours: int,
) -> list[DigestMatchLine]:
    """Сформировать строки digest из materialized предсказаний в окне профиля."""
    end = now.timestamp() + window_hours * 3600
    lines: list[DigestMatchLine] = []
    for prediction in predictions:
        commence = prediction.match_datetime
        if commence is None:
            continue
        commence_utc = (
            commence.replace(tzinfo=UTC) if commence.tzinfo is None else commence.astimezone(UTC)
        )
        if not now.timestamp() <= commence_utc.timestamp() <= end:
            continue
        lines.append(
            DigestMatchLine(
                home_player=str(prediction.home_player or "?"),
                away_player=str(prediction.away_player or "?"),
                commence_utc=commence_utc,
                proba_home=proba_home_from_prediction(prediction),
                pinnacle_home_decimal=None,
                pinnacle_away_decimal=None,
                edge_home=None,
                edge_away=None,
                bet_decision_home=None,
                bet_decision_away=None,
            )
        )
    return lines
