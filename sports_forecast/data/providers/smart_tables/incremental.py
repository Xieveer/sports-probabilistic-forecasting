"""Incremental refresh: nearest-matches + stat-odds sidecar (upcoming/live)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from sports_forecast.data.providers.smart_tables.assembler import bronze_to_row
from sports_forecast.data.providers.smart_tables.catalog import (
    CompetitionEntry,
    filter_national_competitions,
    load_competition_catalog,
)
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.constants import MATCH_LIST_RELATED_ENTITIES
from sports_forecast.data.providers.smart_tables.fetch import fetch_match_bronze
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _extract_nearest_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("items") or data.get("list") or []
    return [x for x in items if isinstance(x, dict)]


def fetch_nearest_match_ids(
    client: SmartTablesApiClient,
    competition: CompetitionEntry,
    *,
    limit: int,
) -> list[int]:
    """Ближайшие матчи турнира через ``/match-center/nearest-matches``."""
    payload = client.get_json(
        "match-center/nearest-matches",
        params={
            "offset": 0,
            "limit": limit,
            "filter[competition_id]": competition.competition_id,
            "relatedEntities": MATCH_LIST_RELATED_ENTITIES,
        },
    )
    ids: list[int] = []
    for item in _extract_nearest_items(payload):
        mid = item.get("id") or item.get("match_id")
        if mid is not None:
            ids.append(int(mid))
    return ids


def fetch_stat_odds_rows(
    client: SmartTablesApiClient,
    match_center_id: int,
    *,
    stat: str = "goals",
    stat_format: str = "totals",
    stat_period: str = "all",
) -> list[dict[str, Any]]:
    """Плоские строки stat-odds для одного match_center (prematch/live)."""
    payload = client.get_json(
        f"match-center/{match_center_id}/stat-odds",
        params={
            "stat": stat,
            "stat_format": stat_format,
            "stat_period": stat_period,
        },
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    stat_node = data.get("stat")
    if not stat_node:
        return []
    return [
        {
            "match_center_id": match_center_id,
            "stat": stat,
            "stat_format": stat_format,
            "stat_period": stat_period,
            "payload_json": json.dumps(stat_node, ensure_ascii=False),
        }
    ]


def run_incremental(
    client: SmartTablesApiClient,
    *,
    catalog_path: str,
    national_teams_only: bool,
    competition_codes: list[str] | None,
    storage_dir: Path,
    output_csv_path: Path,
    raw_root: Path,
    nearest_limit: int,
    stat_odds_sidecar_name: str,
) -> pd.DataFrame:
    """Дополнить ``source.csv`` ближайшими матчами и записать stat-odds sidecar.

    Исторические кэфы **не** обогащаются — только prematch stat-odds ST.
    """
    catalog = load_competition_catalog(catalog_path)
    competitions = filter_national_competitions(
        catalog,
        national_teams_only=national_teams_only,
        competition_codes=competition_codes,
    )

    new_rows: list[dict[str, Any]] = []
    odds_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for comp in competitions:
        for mid in fetch_nearest_match_ids(client, comp, limit=nearest_limit):
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            bronze = fetch_match_bronze(client, mid, raw_root, use_network=True)
            row = bronze_to_row(bronze)
            if row is not None:
                new_rows.append(row)
                mcid = row.get("match_center_id")
                if mcid not in (None, ""):
                    try:
                        odds_rows.extend(fetch_stat_odds_rows(client, int(mcid)))
                    except Exception as e:
                        logger.warning("stat-odds skip match_center_id=%s: %s", mcid, e)

    if output_csv_path.is_file() and new_rows:
        prev = pd.read_csv(output_csv_path, dtype=str, low_memory=False)
        fresh = pd.DataFrame(new_rows)
        combined = pd.concat([prev, fresh], ignore_index=True)
        combined = combined.drop_duplicates(subset=["match_id"], keep="last")
        combined.to_csv(output_csv_path, index=False)
        df = combined
    elif new_rows:
        df = pd.DataFrame(new_rows)
        df.to_csv(output_csv_path, index=False)
    elif output_csv_path.is_file():
        df = pd.read_csv(output_csv_path, dtype=str, low_memory=False)
    else:
        df = pd.DataFrame()

    if odds_rows:
        sidecar = storage_dir / stat_odds_sidecar_name
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(odds_rows).to_parquet(sidecar, index=False)
        logger.info("Smart Tables incremental: stat-odds → %s (%d rows)", sidecar, len(odds_rows))

    logger.info("Smart Tables incremental: %d новых/обновлённых матчей", len(new_rows))
    return df
