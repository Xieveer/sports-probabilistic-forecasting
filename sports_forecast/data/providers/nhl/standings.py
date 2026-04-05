"""Загрузка таблицы турнира NHL на календарную дату (``standings/YYYY-MM-DD``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient


@dataclass(frozen=True)
class StandingRow:
    """Место команды в конференции и накопительные очки/GP на дату снимка."""

    conference_abbrev: str
    conference_rank: int
    points: int
    games_played: int


def _abbr(row: dict[str, Any]) -> str | None:
    raw = row.get("teamAbbrev")
    if isinstance(raw, dict):
        v = raw.get("default")
        return str(v) if v else None
    if isinstance(raw, str):
        return raw
    return None


def parse_standings_payload(payload: dict[str, Any]) -> dict[str, StandingRow]:
    """Разобрать JSON ответа ``standings`` в словарь по аббревиатуре команды.

    Args:
        payload: Тело ответа API с ключом ``standings`` (список строк).

    Returns:
        ``abbr -> StandingRow``; ключ — аббревиатура команды как в ответе API.
    """
    out: dict[str, StandingRow] = {}
    for row in payload.get("standings") or []:
        if not isinstance(row, dict):
            continue
        ab = _abbr(row)
        if not ab:
            continue
        conf = str(row.get("conferenceAbbrev") or "")
        try:
            rank = int(row.get("conferenceSequence", 0))
        except (TypeError, ValueError):
            rank = 0
        try:
            pts = int(row.get("points", 0))
        except (TypeError, ValueError):
            pts = 0
        try:
            gp = int(row.get("gamesPlayed", 0))
        except (TypeError, ValueError):
            gp = 0
        out[ab] = StandingRow(
            conference_abbrev=conf,
            conference_rank=rank,
            points=pts,
            games_played=gp,
        )
    return out


def fetch_standings_for_date(client: NhlApiClient, ymd: str) -> dict[str, StandingRow]:
    """Запросить ``standings/{ymd}`` и вернуть индекс команд.

    Снимок за день ``ymd`` соответствует итогам после игр этого календарного дня
    (в смысле NHL для данного эндпоинта). Для полей «до матча» по полю расписания
    ``gameDate`` используйте :func:`standings_snapshot_ymd_before_game_date`.

    Args:
        client: Клиент NHL API.
        ymd: Дата снимка ``YYYY-MM-DD``.

    Returns:
        Результат :func:`parse_standings_payload` для тела ответа.
    """
    payload = client.get_json(f"standings/{ymd}")
    return parse_standings_payload(payload)


def standings_snapshot_ymd_before_game_date(game_date_ymd: str) -> str:
    """Дата ``YYYY-MM-DD`` для ``standings/…``, дающая срез до игр за ``gameDate``.

    У матча в расписании поле ``gameDate`` — календарный день игры (локальный день NHL).
    Запрос ``standings/{gameDate}`` уже включает результаты матчей за этот день, поэтому
    для *home_GP* / *home_P* / места в конференции **до** данного матча берём снимок
    на **предыдущий** день: ``gameDate - 1``.

    Не учитывает порядок внутри одного ``gameDate``: при нескольких матчах за день
    поздний матч всё равно получит таблицу без учёта более ранних игр того же дня ---
    для этого у Web API нет точного среза по ``startTimeUTC`` без отдельной модели.

    Args:
        game_date_ymd: Значение ``gameDate`` из stub расписания, ``YYYY-MM-DD``.

    Returns:
        Дата для вызова :func:`fetch_standings_for_date`.
    """
    d = date.fromisoformat(game_date_ymd.strip())
    return (d - timedelta(days=1)).isoformat()
