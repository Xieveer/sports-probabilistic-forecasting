"""Общие границы букмекерских суток для календаря и acquisition."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


MOSCOW = ZoneInfo("Europe/Moscow")


def bookmaker_window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """Вернуть UTC окно N суток от ближайшей предыдущей границы 08:00 МСК."""
    if days < 1:
        raise ValueError("Длительность окна должна быть положительной")
    if now.tzinfo is None:
        raise ValueError("Момент начала окна должен содержать часовой пояс")
    local_now = now.astimezone(MOSCOW)
    start = datetime.combine(local_now.date(), time(8), tzinfo=MOSCOW)
    if local_now < start:
        start -= timedelta(days=1)
    return start.astimezone(UTC), (start + timedelta(days=days)).astimezone(UTC)
