"""Доставка terminal Data Cycle уведомлений из transactional outbox."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from html import escape
from typing import Any

from aiogram import Bot
from omegaconf import DictConfig, OmegaConf

from sports_forecast.bot.handlers.admin import ControlApiError, _control_request
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_STATUS_LABELS = {
    "success": "Успешно",
    "partial_success": "Частично успешно",
    "failed": "Ошибка",
}
_POLL_LIMIT = 20


class NotificationConfigurationError(ValueError):
    """Настройки маршрутизации notification outbox отсутствуют или некорректны."""


def validate_notification_destinations(cfg: DictConfig) -> dict[str, int]:
    """Проверить непустое отображение safe alias → ровно один Telegram chat ID."""
    raw = cfg.bot.get("notification_destinations")
    if raw is None:
        raise NotificationConfigurationError("Не заданы notification destinations")
    if isinstance(raw, DictConfig):
        raw = OmegaConf.to_container(raw, resolve=True)
    if not isinstance(raw, Mapping) or not raw:
        raise NotificationConfigurationError("Не заданы notification destinations")

    destinations: dict[str, int] = {}
    for alias, raw_chat_ids in raw.items():
        if not isinstance(alias, str) or _ALIAS_PATTERN.fullmatch(alias) is None:
            raise NotificationConfigurationError("Некорректный notification destination alias")
        if isinstance(raw_chat_ids, (list, tuple)):
            raise NotificationConfigurationError(
                "Каждый alias должен содержать один Telegram destination; "
                "несколько получателей задайте разными aliases"
            )
        if isinstance(raw_chat_ids, bool) or not isinstance(raw_chat_ids, (int, str)):
            raise NotificationConfigurationError("Некорректный Telegram destination")
        candidate = str(raw_chat_ids).strip()
        if not candidate or re.fullmatch(r"-?[0-9]+", candidate) is None:
            raise NotificationConfigurationError("Некорректный Telegram destination")
        destinations[alias] = int(candidate)
    if not destinations:
        raise NotificationConfigurationError("Не заданы notification destinations")
    return destinations


def _count(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return "n/a"


def _coverage(value: object) -> str:
    if not isinstance(value, Mapping):
        return "n/a"
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not (
        isinstance(numerator, int)
        and not isinstance(numerator, bool)
        and numerator >= 0
        and isinstance(denominator, int)
        and not isinstance(denominator, bool)
        and denominator >= 0
    ):
        return "n/a"
    return f"{numerator}/{denominator}"


def format_terminal_notification(notification: Mapping[str, Any]) -> str:
    """Сформировать короткий HTML summary только из allow-listed полей."""
    pipeline = escape(str(notification.get("pipeline_id") or "неизвестен"))
    run_id = escape(str(notification.get("run_id") or "неизвестен"))
    reason = escape(str(notification.get("reason") or "неизвестна"))
    raw_status = str(notification.get("status") or "неизвестен")
    status = escape(_STATUS_LABELS.get(raw_status, raw_status))
    summary = notification.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    lines = [
        f"<b>Итог Data Cycle · {pipeline.upper()}</b>",
        f"Run ID: <code>{run_id}</code>",
        f"Результат: {status}; запуск: {reason}",
        f"Событий: {_count(summary.get('events_found'))}; "
        f"прогнозы: {_coverage(summary.get('prediction_coverage'))}; "
        f"коэффициенты: {_coverage(summary.get('odds_coverage'))}",
    ]
    duration = summary.get("duration_seconds")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
        lines.append(f"Длительность: {duration:g} с")
    failure_code = notification.get("failure_code")
    if raw_status == "failed" and isinstance(failure_code, str) and failure_code:
        lines.append(f"Код ошибки: <code>{escape(failure_code)}</code>")
    return "\n".join(lines)


async def poll_notifications_once(cfg: DictConfig, bot: Bot) -> int:
    """Забрать ограниченную партию и доставить её по настроенным destination aliases."""
    destinations = validate_notification_destinations(cfg)
    admin_ids = sorted(
        int(value) for value in (cfg.bot.get("admin_user_ids") or []) if value is not None
    )
    if not admin_ids:
        raise NotificationConfigurationError("Не настроен администратор control API")
    admin_id = admin_ids[0]
    batch = await _control_request(
        cfg,
        admin_id,
        "POST",
        "notifications/claim",
        payload={"limit": _POLL_LIMIT},
    )
    notifications = batch.get("notifications")
    if not isinstance(notifications, list):
        raise ControlApiError

    acknowledged = 0
    for item in notifications:
        if not isinstance(item, dict):
            continue
        notification_id = item.get("notification_id")
        lease_token = item.get("lease_token")
        alias = item.get("destination_alias")
        chat_ids = destinations.get(alias) if isinstance(alias, str) else None
        if chat_ids is None:
            logger.warning("Outbox destination alias is not configured")
            continue
        if (
            isinstance(notification_id, bool)
            or not isinstance(notification_id, int)
            or notification_id < 1
        ):
            continue
        if not isinstance(lease_token, str) or not lease_token:
            continue

        message = format_terminal_notification(item)
        send_failed = False
        try:
            await bot.send_message(chat_id=chat_ids, text=message)
        except Exception:
            logger.warning("Telegram outbox delivery failed")
            send_failed = True
        if send_failed:
            try:
                await _control_request(
                    cfg,
                    admin_id,
                    "POST",
                    f"notifications/{notification_id}/retry",
                    payload={
                        "lease_token": lease_token,
                        "error_code": "telegram_send_failed",
                    },
                )
            except ControlApiError:
                logger.warning("Outbox retry request failed")
            continue

        try:
            await _control_request(
                cfg,
                admin_id,
                "POST",
                f"notifications/{notification_id}/ack",
                payload={"lease_token": lease_token},
            )
        except ControlApiError:
            logger.warning("Outbox acknowledgement failed after Telegram send")
            continue
        acknowledged += 1
    return acknowledged


async def notification_poll_loop(
    cfg: DictConfig, bot: Bot, *, interval_seconds: float = 10.0
) -> None:
    """Постоянно опрашивать outbox; сбой итерации не останавливает Telegram bot."""
    while True:
        try:
            await poll_notifications_once(cfg, bot)
        except (ControlApiError, NotificationConfigurationError):
            logger.warning("Telegram notification outbox is unavailable or misconfigured")
        except Exception:
            logger.warning("Telegram notification poll failed")
        await asyncio.sleep(interval_seconds)
