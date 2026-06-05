"""Константы Smart Tables ingest: stat-коды, периоды, relatedEntities."""

from __future__ import annotations


# 11 метрик сборных (единый набор для WC / EURO / FRII / …)
STAT_CODES: tuple[str, ...] = (
    "goals",
    "xg",
    "corners",
    "yellowcards",
    "offsides",
    "shotstarget",
    "attacks",
    "dattacks",
    "possession",
    "redcards",
    "yellowcards_bet365",
)

# API period → suffix в wide-колонках
PERIOD_API_TO_SUFFIX: dict[str, str] = {
    "all": "all",
    "first": "1h",
    "second": "2h",
}

PERIODS_API: tuple[str, ...] = tuple(PERIOD_API_TO_SUFFIX.keys())

MATCH_CARD_RELATED_ENTITIES: str = "home_team_with_coach,away_team_with_coach,referee,competition"

MATCH_LIST_RELATED_ENTITIES: str = "home_team,away_team"
