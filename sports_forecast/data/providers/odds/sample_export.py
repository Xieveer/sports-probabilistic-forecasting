"""Сводка нескольких событий The Odds API в таблицу для CSV/быстрых проверок."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd

from sports_forecast.data.providers.odds.enrichment import events_to_odds_frame


if TYPE_CHECKING:
    from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry


def bookmaker_keys_from_event(ev: dict[str, Any]) -> str:
    """Ключи ``bookmakers[].key`` через ``|`` в алфавитном порядке."""
    keys: list[str] = []
    for bm in ev.get("bookmakers") or []:
        if isinstance(bm, dict) and bm.get("key") is not None:
            keys.append(str(bm["key"]))
    return "|".join(sorted(keys))


def events_to_match_sample_dataframe(
    events: Sequence[dict[str, Any]],
    book_cfg: Any,
    *,
    team_registry: TeamNameRegistry | None = None,
    limit: int = 8,
) -> pd.DataFrame:
    """Первые ``limit`` событий → одна строка на матч (V3 close + колонка букмекеров из JSON).

    Args:
        events: Список событий из ``unwrap_odds_payload``.
        book_cfg: Узел конфига с ``bookmaker_profiles`` (как ``book_root`` в backfill).
        team_registry: :class:`~sports_forecast.data.providers.odds.team_name_registry.TeamNameRegistry`.
        limit: Максимум строк.

    Returns:
        DataFrame; при отсутствии событий — пустой кадр без лишних колонок.
    """
    evs: list[dict[str, Any]] = []
    for ev in events:
        if isinstance(ev, dict) and len(evs) < max(0, limit):
            evs.append(ev)
    if not evs:
        return events_to_odds_frame(
            [], None, "pinnacle", {}, book_cfg=book_cfg, team_registry=team_registry
        )

    df = events_to_odds_frame(
        evs,
        None,
        "pinnacle",
        {},
        book_cfg=book_cfg,
        team_registry=team_registry,
    )
    if df.empty:
        return df
    keys_col = [bookmaker_keys_from_event(e) for e in evs]
    if len(keys_col) != len(df):
        # Порядок строк совпадает с ``evs`` в enrichment; на всякий случай усечь.
        keys_col = keys_col[: len(df)]
    out = df.copy()
    out.insert(0, "bookmakers_in_event", keys_col)
    return out
