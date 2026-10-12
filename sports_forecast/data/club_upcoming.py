"""Отдельный снимок ближайших клубных матчей Smart Tables для локального E2E."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from sports_forecast.data.providers.smart_tables.assembler import bronze_to_row
from sports_forecast.data.providers.smart_tables.catalog import CompetitionEntry
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.incremental import fetch_nearest_match_ids


def normalize_match_center_upcoming(
    payload: dict[str, Any],
    competition: CompetitionEntry,
    observed_at: datetime,
    *,
    requested_id: int,
) -> dict[str, Any] | None:
    """Привести будущий match-center к схеме исторического Smart Tables CSV."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    item = data.get("item")
    teams = data.get("teams")
    if not isinstance(item, dict) or not isinstance(teams, dict):
        return None
    if str(item.get("id")) != str(requested_id):
        return None
    if int(item.get("competition_id") or -1) != competition.competition_id:
        return None
    if str(item.get("status", "")).strip() != "not-started":
        return None
    if item.get("home_goals") is not None or item.get("away_goals") is not None:
        return None
    scheduled = pd.to_datetime(item.get("begin_at"), utc=True, errors="coerce")
    if pd.isna(scheduled) or scheduled.to_pydatetime() <= observed_at:
        return None
    home = teams.get("home")
    away = teams.get("away")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    home_id = home.get("id")
    away_id = away.get("id")
    if not home_id or not away_id or str(home_id) == str(away_id):
        return None
    if not str(home.get("common_title") or home.get("title") or "").strip():
        return None
    if not str(away.get("common_title") or away.get("title") or "").strip():
        return None
    if item.get("home_team_id") is not None and str(item["home_team_id"]) != str(home_id):
        return None
    if item.get("away_team_id") is not None and str(item["away_team_id"]) != str(away_id):
        return None
    match_center_id = item.get("id")
    card = dict(item)
    card["id"] = f"mc:{match_center_id}"
    card["match_center_id"] = match_center_id
    card["begin_at"] = scheduled.strftime("%Y-%m-%d %H:%M:%S")
    card["home_team_with_coach"] = home
    card["away_team_with_coach"] = away
    card["competition"] = {**(item.get("competition") or {}), "code": competition.code}
    return bronze_to_row({"card": {"data": {"item": card}}}, national_teams_only=False)


def fetch_club_upcoming(
    client: SmartTablesApiClient,
    competitions: list[CompetitionEntry],
    *,
    limit: int,
    observed_at: datetime,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Опросить все соревнования пула и вернуть валидные будущие строки."""
    rows: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    seen: set[str] = set()
    for competition in competitions:
        count = 0
        for match_center_id in fetch_nearest_match_ids(client, competition, limit=limit):
            payload = client.get_json(f"match-center/{match_center_id}")
            row = normalize_match_center_upcoming(
                payload, competition, observed_at, requested_id=match_center_id
            )
            if row is None:
                continue
            match_id = str(row["match_id"])
            if match_id in seen:
                continue
            seen.add(match_id)
            rows.append(row)
            count += 1
        coverage[competition.code] = count
    return pd.DataFrame(rows), coverage


def write_upcoming_snapshot(
    frame: pd.DataFrame,
    coverage: dict[str, int],
    path: Path,
    *,
    observed_at: datetime,
) -> Path:
    """Сохранить source CSV и компактный manifest с provenance."""
    if frame.empty:
        raise ValueError("Smart Tables не вернул будущих клубных матчей")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    manifest_path = path.with_suffix(".snapshot.json")
    manifest_path.write_text(
        json.dumps(
            {
                "source": "smart_tables",
                "observed_at": observed_at.astimezone(UTC).isoformat(),
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "coverage": coverage,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path
