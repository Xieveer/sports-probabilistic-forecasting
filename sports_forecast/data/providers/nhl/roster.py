"""Составы команд: эндпоинт ``roster/{TEAM}/{SEASON_ID}``, упаковка в строку для CSV."""

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
    """Получить сырой JSON состава команды на сезон.

    Args:
        client: Клиент NHL API.
        team_abbr: Трёхбуквенный код команды (например ``PIT``).
        season_id: Восьмизначный идентификатор сезона (например ``20252026``).

    Returns:
        Объект API с группами ``forwards``, ``defensemen``, ``goalies``.
    """
    path = f"roster/{team_abbr}/{season_id}"
    return client.get_json(path)


def roster_to_json_cell(client: NhlApiClient, team_abbr: str, season_id: int) -> str:
    """Сериализовать состав в одну строку для ячейки CSV.

    Args:
        client: Клиент NHL API.
        team_abbr: Код команды.
        season_id: Идентификатор сезона.

    Returns:
        JSON-строка с полями ``team``, ``season``, ``players``, ``injured`` (травмы
        пока всегда пустой список — отдельного фида в Web API нет).
    """
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
