"""Составы команд по ``roster/{TEAM}/{SEASON_ID}``."""

from __future__ import annotations

import json
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient


def _name_cell(node: Any) -> str:
    if isinstance(node, dict):
        v = node.get("default")
        return str(v) if v is not None else ""
    if node is None:
        return ""
    return str(node)


def _compact_player(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "playerId": p.get("playerId") or p.get("id"),
        "firstName": _name_cell(p.get("firstName")),
        "lastName": _name_cell(p.get("lastName")),
        "positionCode": p.get("positionCode") or p.get("position"),
        "sweaterNumber": p.get("sweaterNumber"),
    }


def fetch_roster_payload(client: NhlApiClient, team_abbr: str, season_id: int) -> dict[str, Any]:
    """Сырой JSON состава."""
    path = f"roster/{team_abbr}/{season_id}"
    return client.get_json(path)


def roster_to_json_cell(client: NhlApiClient, team_abbr: str, season_id: int) -> str:
    """Один столбец CSV: JSON со списком игроков (без внешних вложенностей)."""
    payload = fetch_roster_payload(client, team_abbr, season_id)
    players: list[dict[str, Any]] = []
    for group in ("forwards", "defensemen", "goalies"):
        for ply in payload.get(group) or []:
            if isinstance(ply, dict):
                players.append(_compact_player(ply))
    blob = {
        "team": team_abbr,
        "season": season_id,
        "players": players,
        "injured": [],
    }
    return json.dumps(blob, ensure_ascii=False)
