"""Backfill A–B: пагинация списка матчей по competition_id с checkpoint и кэшем."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sports_forecast.data.providers.smart_tables.catalog import CompetitionEntry
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.constants import MATCH_LIST_RELATED_ENTITIES
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class MatchesListCheckpoint:
    """Состояние пагинации списков матчей."""

    competition_id: int
    offset: int


def _load_list_checkpoint(path: Path) -> MatchesListCheckpoint | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return MatchesListCheckpoint(
            competition_id=int(raw["competition_id"]),
            offset=int(raw["offset"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _save_list_checkpoint(path: Path, ck: MatchesListCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"competition_id": ck.competition_id, "offset": ck.offset}, indent=2),
        encoding="utf-8",
    )


def _list_cache_path(cache_dir: Path, competition_id: int, offset: int) -> Path:
    return cache_dir / f"{competition_id}_{offset}.json"


def _extract_match_ids(payload: dict[str, Any]) -> tuple[list[int], int]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return [], 0
    items = data.get("items") or data.get("list") or []
    if not isinstance(items, list):
        items = []
    ids: list[int] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(int(item["id"]))
    total = int(data.get("total") or len(ids))
    return ids, total


def collect_match_ids(
    client: SmartTablesApiClient,
    competitions: list[CompetitionEntry],
    *,
    page_limit: int,
    cache_dir: Path,
    checkpoint_path: Path | None,
    use_network: bool = True,
) -> list[int]:
    """Собрать уникальные ``match_id`` по всем турнирам (с resume checkpoint).

    Args:
        client: HTTP-клиент (или mock).
        competitions: Отфильтрованный каталог.
        page_limit: ``limit`` для ``GET /matches``.
        cache_dir: Каталог bronze-кэша списков.
        checkpoint_path: JSON checkpoint ``(competition_id, offset)``; ``None`` — без resume.
        use_network: ``False`` — только читать кэш (для тестов).

    Returns:
        Уникальные match_id в порядке обхода.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_ids: list[int] = []
    seen: set[int] = set()

    start_comp_idx = 0
    start_offset = 0
    ck = _load_list_checkpoint(checkpoint_path) if checkpoint_path else None
    if ck is not None:
        for i, comp in enumerate(competitions):
            if comp.competition_id == ck.competition_id:
                start_comp_idx = i
                start_offset = ck.offset
                break

    for comp_idx in range(start_comp_idx, len(competitions)):
        comp = competitions[comp_idx]
        offset = start_offset if comp_idx == start_comp_idx else 0
        start_offset = 0

        while True:
            cache_file = _list_cache_path(cache_dir, comp.competition_id, offset)
            if cache_file.is_file():
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
            elif use_network:
                payload = client.get_json(
                    "matches",
                    params={
                        "offset": offset,
                        "limit": page_limit,
                        "filter[competition_id]": comp.competition_id,
                        "orderBy": "begin_at",
                        "orderDir": "DESC",
                        "relatedEntities": MATCH_LIST_RELATED_ENTITIES,
                    },
                )
                cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            else:
                logger.warning(
                    "Нет кэша списка competition_id=%s offset=%s",
                    comp.competition_id,
                    offset,
                )
                break

            page_ids, total = _extract_match_ids(payload)
            for mid in page_ids:
                if mid not in seen:
                    seen.add(mid)
                    all_ids.append(mid)

            next_offset = offset + page_limit
            if checkpoint_path is not None:
                _save_list_checkpoint(
                    checkpoint_path,
                    MatchesListCheckpoint(competition_id=comp.competition_id, offset=next_offset),
                )

            if next_offset >= total or not page_ids:
                break
            offset = next_offset

        logger.info(
            "Smart Tables list: competition %s (%s) — накоплено %d match_id",
            comp.code,
            comp.competition_id,
            len(all_ids),
        )

    if checkpoint_path is not None and checkpoint_path.is_file():
        checkpoint_path.unlink()
        logger.info("Smart Tables: удалён checkpoint списков матчей %s", checkpoint_path)

    return all_ids
