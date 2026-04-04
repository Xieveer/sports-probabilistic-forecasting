"""Таблица: snapshot на дату ``standings/YYYY-MM-DD``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient


@dataclass(frozen=True)
class StandingRow:
    """Строка standings для одной команды."""

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
    """Преобразовать ответ API в индекс по аббревиатуре команды."""
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
    """Загрузить ``standings/{YYYY-MM-DD}``."""
    payload = client.get_json(f"standings/{ymd}")
    return parse_standings_payload(payload)
