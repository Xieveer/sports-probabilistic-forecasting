"""Однозначная проекция OddsStore в canonical event identity."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.service.db.models import CanonicalEvent
from sports_forecast.service.db.repository import CalendarRepository


@dataclass(frozen=True)
class OddsMarketColumns:
    """Колонки OddsStore, описывающие обязательные значения одного рынка."""

    market: str
    market_spec: str
    bookmaker: str
    value_columns: tuple[str, ...]
    provider_timestamp_column: str | None = None


@dataclass(frozen=True)
class OddsObservationInput:
    """Нормализованное наблюдение линии до его записи в DB."""

    canonical_event_id: int
    market: str
    market_spec: str
    bookmaker: str
    event_scheduled_at: datetime
    event_home_participant: str
    event_away_participant: str
    observed_at: datetime
    values: dict[str, float]
    source: str


def _parse_timestamp(value: Any) -> datetime | None:
    """Разобрать provider/store timestamp и нормализовать к UTC."""
    if value is None or pd.isna(value):
        return None
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return None
    return cast(datetime, timestamp.to_pydatetime()).astimezone(UTC)


def project_odds_rows(
    events: Sequence[Any],
    odds_rows: pd.DataFrame,
    market_columns: Sequence[OddsMarketColumns],
    team_registry: TeamNameRegistry,
    *,
    source: str = "the_odds_api",
) -> list[OddsObservationInput]:
    """Сопоставить линии с событием по уникальным командам и точному kickoff.

    Строки без фактического ``fetched_at``, точного времени начала, валидной
    линии или однозначного canonical event игнорируются. Совпадение только по
    дате намеренно недостаточно.
    """
    if odds_rows.empty:
        return []
    event_index: dict[tuple[str, str, datetime], list[Any]] = {}
    for event in events:
        kickoff = _parse_timestamp(event.scheduled_at)
        home = team_registry.resolve(event.home_participant or "")
        away = team_registry.resolve(event.away_participant or "")
        if kickoff is not None and home and away:
            event_index.setdefault((home, away, kickoff), []).append(event)

    output: list[OddsObservationInput] = []
    for _, row in odds_rows.iterrows():
        kickoff = _parse_timestamp(row.get("commence_time_utc"))
        home = team_registry.resolve(str(row.get("home_team_norm") or ""))
        away = team_registry.resolve(str(row.get("away_team_norm") or ""))
        candidates = event_index.get((home, away, kickoff), []) if kickoff is not None else []
        if len(candidates) != 1:
            continue
        event = candidates[0]
        event_scheduled_at = _parse_timestamp(event.scheduled_at)
        if event_scheduled_at is None:
            continue
        for market in market_columns:
            observed_at = (
                _parse_timestamp(row.get(market.provider_timestamp_column))
                if market.provider_timestamp_column
                else None
            )
            if observed_at is None:
                continue
            values: dict[str, float] = {}
            for column in market.value_columns:
                raw_value = row.get(column)
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    values = {}
                    break
                if not math.isfinite(value) or value <= 1.0:
                    values = {}
                    break
                values[column] = value
            if values:
                output.append(
                    OddsObservationInput(
                        canonical_event_id=int(event.id),
                        market=market.market,
                        market_spec=market.market_spec,
                        bookmaker=market.bookmaker,
                        event_scheduled_at=event_scheduled_at,
                        event_home_participant=str(event.home_participant),
                        event_away_participant=str(event.away_participant),
                        observed_at=observed_at,
                        values=values,
                        source=source,
                    )
                )
    return output


def sync_odds_store_observations(
    session: Session,
    tournament: str,
    odds_rows: pd.DataFrame,
    policy: dict[str, Any],
    team_registry: TeamNameRegistry,
) -> int:
    """Перенести однозначные подтверждённые OddsStore строки в service DB."""
    events = list(
        session.scalars(select(CanonicalEvent).where(CanonicalEvent.tournament == tournament)).all()
    )
    specs = [
        OddsMarketColumns(
            market=str(item["market"]),
            market_spec=str(item["market_spec"]),
            bookmaker=str(item["bookmaker"]),
            value_columns=tuple(str(value) for value in item["value_columns"]),
            provider_timestamp_column=(
                str(item["provider_timestamp_column"])
                if item.get("provider_timestamp_column")
                else None
            ),
        )
        for item in policy.get("odds_markets", [])
    ]
    observations = project_odds_rows(events, odds_rows, specs, team_registry)
    repository = CalendarRepository(session)
    return sum(repository.upsert_odds_observation(item) for item in observations)
