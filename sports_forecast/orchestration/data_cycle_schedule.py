"""Общие правила расписания для API и host dispatcher."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ALLOWED_INTERVAL_HOURS = frozenset({4, 6, 8, 12, 24})
SUPPORTED_TIMEZONES = frozenset({"Europe/Moscow"})


def validate_schedule(base_time: str, timezone: str, interval_hours: int) -> time:
    """Проверить business schedule и вернуть базовое локальное время."""
    try:
        parsed_time = time.fromisoformat(base_time)
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Некорректное время или IANA timezone расписания") from exc
    if parsed_time.tzinfo is not None or parsed_time.second or parsed_time.microsecond:
        raise ValueError("Основное время должно иметь формат HH:MM")
    if timezone not in SUPPORTED_TIMEZONES:
        raise ValueError("Для этого pipeline пока поддерживается только Europe/Moscow")
    if interval_hours not in ALLOWED_INTERVAL_HOURS:
        raise ValueError("Интервал отсутствует в допустимом списке расписания")
    return parsed_time


def next_scheduled_at(
    base_time: str,
    timezone: str,
    interval_hours: int,
    now: datetime,
) -> datetime:
    """Вернуть следующий слот по локальному времени, сериализованный в UTC."""
    parsed_time = validate_schedule(base_time, timezone, interval_hours)
    if now.tzinfo is None:
        raise ValueError("Для расчёта слота требуется timezone-aware момент")

    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    local_base = datetime.combine(local_now.date(), parsed_time, tzinfo=zone)
    interval = timedelta(hours=interval_hours)
    for day_offset in range(0, 3):
        anchor = local_base + timedelta(days=day_offset)
        for slot_index in range(24 // interval_hours):
            candidate = anchor + interval * slot_index
            if candidate > local_now:
                return candidate.astimezone(UTC)
    raise RuntimeError("Не удалось вычислить следующий слот расписания")
