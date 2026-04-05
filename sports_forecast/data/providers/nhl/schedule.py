"""Итерация по календарю и загрузка расписания NHL (эндпоинт ``schedule/{YYYY-MM-DD}``)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class ScheduleGameStub:
    """Сводка матча, извлечённая из JSON расписания (до запросов boxscore)."""

    game_id: int
    season: int
    game_type: int
    game_date: str
    start_time_utc: str
    venue_default: str
    home_abbrev: str
    away_abbrev: str
    game_state: str
    match_end: str | None
    home_score: int | None
    away_score: int | None


def _local_default(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and "default" in node:
        v = node["default"]
        return str(v) if v is not None else None
    return str(node)


def _parse_game(
    g: dict[str, Any],
    fallback_game_date: str | None = None,
) -> ScheduleGameStub | None:
    gid = g.get("id")
    if gid is None:
        return None
    season = g.get("season")
    if season is None:
        return None
    gt = g.get("gameType")
    if gt is None:
        return None
    gdate = g.get("gameDate") or fallback_game_date
    st = g.get("startTimeUTC")
    if not gdate and isinstance(st, str) and len(st) >= 10:
        gdate = st[:10]
    if not gdate:
        return None
    if not st:
        return None
    venue = g.get("venue") or {}
    ht = g.get("homeTeam") or {}
    at = g.get("awayTeam") or {}
    ha = _local_default(ht.get("abbrev"))
    aa = _local_default(at.get("abbrev"))
    if not ha or not aa:
        return None
    outcome = g.get("gameOutcome") or {}
    last_pt = outcome.get("lastPeriodType")
    match_end = str(last_pt) if last_pt else None
    hscore = ht.get("score")
    ascore = at.get("score")
    return ScheduleGameStub(
        game_id=int(gid),
        season=int(season),
        game_type=int(gt),
        game_date=str(gdate),
        start_time_utc=str(st),
        venue_default=_local_default(venue) or "",
        home_abbrev=str(ha),
        away_abbrev=str(aa),
        game_state=str(g.get("gameState") or ""),
        match_end=match_end,
        home_score=int(hscore) if hscore is not None else None,
        away_score=int(ascore) if ascore is not None else None,
    )


def iter_week_starts(d0: date, d1: date) -> Iterator[date]:
    """Даты-якоря с шагом 7 дней от ``d0`` до ``d1`` включительно.

    Args:
        d0: Первая дата недельного окна API.
        d1: Последняя дата (включительно).

    Yields:
        Календарные даты для вызова :func:`fetch_schedule_day`.
    """
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=7)


def fetch_schedule_day(client: NhlApiClient, day: date) -> list[ScheduleGameStub]:
    """Запросить ``schedule/{day}`` и распарсить все матчи из ``gameWeek``.

    Args:
        client: Клиент NHL API.
        day: Дата якоря в формате календаря Python.

    Returns:
        Список :class:`ScheduleGameStub` (без дедупликации между якорями).
    """
    path = f"schedule/{day.isoformat()}"
    payload = client.get_json(path)
    out: list[ScheduleGameStub] = []
    for week in payload.get("gameWeek") or []:
        wk_date = week.get("date") if isinstance(week, dict) else None
        wk_date_s = str(wk_date) if wk_date else None
        for g in week.get("games") or []:
            if not isinstance(g, dict):
                continue
            stub = _parse_game(g, fallback_game_date=wk_date_s)
            if stub is not None:
                out.append(stub)
    return out


def collect_games_for_range(
    client: NhlApiClient,
    date_from: date,
    date_to: date,
    season_min: int | None,
    season_max: int | None,
    finished_only: bool = True,
) -> dict[int, ScheduleGameStub]:
    """Собрать уникальные матчи за интервал дат (недельные запросы).

    Args:
        client: NHL API клиент.
        date_from: Начало интервала (включительно).
        date_to: Конец интервала (включительно).
        season_min: Нижняя граница поля season (8-значный SEASON_ID); None — без фильтра.
        season_max: Верхняя граница season; None — без фильтра.
        finished_only: Если True — только ``gameState == OFF``.

    Returns:
        Словарь ``game_id -> stub``.

    Note:
        На уровне INFO логируется старт, каждый недельный якорь и итоговое число
        уникальных матчей после фильтров.
    """
    by_id: dict[int, ScheduleGameStub] = {}
    anchors = list(iter_week_starts(date_from, date_to))
    logger.info(
        "NHL schedule: сбор с %s по %s, недельных якорей: %d, finished_only=%s, "
        "season_id in [%s, %s]",
        date_from.isoformat(),
        date_to.isoformat(),
        len(anchors),
        finished_only,
        season_min if season_min is not None else "—",
        season_max if season_max is not None else "—",
    )
    for anchor in anchors:
        batch = fetch_schedule_day(client, anchor)
        before = len(by_id)
        for stub in batch:
            if season_min is not None and stub.season < season_min:
                continue
            if season_max is not None and stub.season > season_max:
                continue
            if finished_only and stub.game_state != "OFF":
                continue
            by_id[stub.game_id] = stub
        added = len(by_id) - before
        logger.info(
            "NHL schedule: якорь %s, матчей в ответе: %d, новых после фильтров: %d, "
            "всего уникальных: %d",
            anchor.isoformat(),
            len(batch),
            added,
            len(by_id),
        )
    logger.info("NHL schedule: готово, уникальных матчей: %d", len(by_id))
    return by_id
