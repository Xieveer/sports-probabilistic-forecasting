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


def _optional_scalar(v: Any) -> Any | None:
    """Вернуть скаляр для JSON или ``None``, если значения нет (ключ тогда не добавляем)."""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _compact_draft(p: dict[str, Any]) -> dict[str, Any] | None:
    """Собрать опциональный блок черновика из плоских полей и/или ``draftDetails``."""
    merged: dict[str, Any] = {}
    nested = p.get("draftDetails")
    if isinstance(nested, dict):
        for k in (
            "year",
            "draftYear",
            "round",
            "draftRound",
            "overallPick",
            "overall",
            "pickInRound",
            "draftPickInRound",
        ):
            ov = _optional_scalar(nested.get(k))
            if ov is not None:
                merged[k] = ov
    for k in ("draftYear", "draftRound", "draftOverall"):
        ov = _optional_scalar(p.get(k))
        if ov is not None and k not in merged:
            merged[k] = ov
    return merged or None


def _compact_player(p: dict[str, Any]) -> dict[str, Any]:
    """Уплотнённый игрок для JSON-ячейки: базовые поля + опциональные, если есть в API."""
    bd = p.get("birthDate") or p.get("birthDateLocalized") or p.get("birthdate")
    out: dict[str, Any] = {
        "playerId": p.get("playerId") or p.get("id"),
        "firstName": _name_cell(p.get("firstName")),
        "lastName": _name_cell(p.get("lastName")),
        "positionCode": p.get("positionCode") or p.get("position"),
        "sweaterNumber": p.get("sweaterNumber"),
        "birthDate": str(bd).strip() if bd else "",
    }
    for key in (
        "heightInInches",
        "heightInCm",
        "weightInPounds",
        "weightInKg",
    ):
        ov = _optional_scalar(p.get(key))
        if ov is not None:
            out[key] = ov
    sc = p.get("shootsCatches")
    if sc is not None and str(sc).strip():
        out["shootsCatches"] = str(sc).strip()
    draft = _compact_draft(p)
    if draft is not None:
        out["draft"] = draft
    return out


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
        JSON-строка с полями ``team``, ``season``, ``players``, ``injured``.
        Список ``injured`` берётся из ответа API, если есть; иначе пустой (типичный
        сезонный roster Web API травм не отдаёт — см. R19.20 для наполнения).
    """
    payload = fetch_roster_payload(client, team_abbr, season_id)
    players: list[dict[str, Any]] = []
    for group in ("forwards", "defensemen", "goalies"):
        for ply in payload.get(group) or []:
            if isinstance(ply, dict):
                players.append(_compact_player(ply))
    injured: list[Any] = []
    raw_injured = payload.get("injured")
    if isinstance(raw_injured, list):
        injured = raw_injured
    blob = {
        "team": team_abbr,
        "season": season_id,
        "players": players,
        "injured": injured,
    }
    return json.dumps(blob, ensure_ascii=False)
