"""Однозначная проекция OddsStore в canonical event identity."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.identity.events import registry_event_reader_enabled
from sports_forecast.identity.installation import pin_installed_registry
from sports_forecast.service.db.models import CanonicalEvent
from sports_forecast.service.db.repository import CalendarRepository
from sports_forecast.service.registry_candidate_capture import enqueue_unknown_designation


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
    retrieved_at: datetime | None = None
    provider_event_id: str | None = None
    registry_snapshot_id: str | None = None


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
    registry_project_events: Mapping[int, tuple[str, str, str, str]] | None = None,
    confirmed_bookmaker_teams: Mapping[tuple[str, str, datetime], str] | None = None,
    registry_snapshot_id: str | None = None,
) -> list[OddsObservationInput]:
    """Сопоставить линии с событием по уникальным командам и точному kickoff.

    Строки без фактического ``fetched_at``, точного времени начала, валидной
    линии или однозначного canonical event игнорируются. Совпадение только по
    дате намеренно недостаточно.
    """
    if odds_rows.empty:
        return []
    if (registry_project_events is None) != (confirmed_bookmaker_teams is None):
        raise ValueError("Strict odds matching требует оба набора registry facts")
    strict = registry_project_events is not None
    event_index: dict[tuple[str, str, datetime] | tuple[str, str, str, datetime], list[Any]] = {}
    for event in events:
        kickoff = _parse_timestamp(event.scheduled_at)
        if strict:
            assert registry_project_events is not None
            project = registry_project_events.get(int(event.id))
            if kickoff is not None and project is not None:
                _, league_id, home_id, away_id = project
                event_index.setdefault((league_id, home_id, away_id, kickoff), []).append(event)
        else:
            home = team_registry.resolve(event.home_participant or "")
            away = team_registry.resolve(event.away_participant or "")
            if kickoff is not None and home and away:
                event_index.setdefault((home, away, kickoff), []).append(event)

    output: list[OddsObservationInput] = []
    for _, row in odds_rows.iterrows():
        kickoff = _parse_timestamp(row.get("commence_time_utc"))
        home_raw = str(row.get("home_team_norm") or "")
        away_raw = str(row.get("away_team_norm") or "")
        if strict:
            assert confirmed_bookmaker_teams is not None
            candidates = []
            if kickoff is not None:
                for league_id in {key[0] for key in event_index}:
                    resolved_home_id = confirmed_bookmaker_teams.get((league_id, home_raw, kickoff))
                    resolved_away_id = confirmed_bookmaker_teams.get((league_id, away_raw, kickoff))
                    if resolved_home_id is not None and resolved_away_id is not None:
                        candidates.extend(
                            event_index.get(
                                (league_id, resolved_home_id, resolved_away_id, kickoff), []
                            )
                        )
        else:
            home = team_registry.resolve(home_raw)
            away = team_registry.resolve(away_raw)
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
                        retrieved_at=_parse_timestamp(row.get("fetched_at")),
                        registry_snapshot_id=registry_snapshot_id,
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
        session.scalars(
            select(CanonicalEvent).where(CanonicalEvent.__table__.c.tournament == tournament)
        ).all()
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
    if registry_event_reader_enabled():
        reader = pin_installed_registry(session)
        project_by_id = {event.id: event for event in reader.event_snapshot.event_snapshot.events}
        registry_project_events: dict[int, tuple[str, str, str, str]] = {}
        league_sports: dict[str, str] = {}
        for event in events:
            try:
                mapping = reader.get_event_mapping(int(event.id), session)
            except KeyError:
                continue
            if mapping.status != "resolved" or mapping.project_event_id is None:
                continue
            project = project_by_id.get(mapping.project_event_id)
            if project is None or project.sport != event.sport:
                continue
            registry_project_events[int(event.id)] = (
                project.id,
                project.tournament_id,
                project.home_team_id,
                project.away_team_id,
            )
            league_sports[project.tournament_id] = project.sport
        confirmed: dict[tuple[str, str, datetime], str] = {}
        seen_candidates: set[tuple[str, str]] = set()
        for _, row in odds_rows.iterrows():
            kickoff = _parse_timestamp(row.get("commence_time_utc"))
            if kickoff is None:
                continue
            for league_id, sport in league_sports.items():
                for raw in (
                    str(row.get("home_team_norm") or ""),
                    str(row.get("away_team_norm") or ""),
                ):
                    result = reader.resolve_designation(
                        source="the_odds_api",
                        kind="team",
                        scope={"sport": sport, "tournament": league_id},
                        value_kind="name",
                        raw_value=raw,
                        at=kickoff.isoformat(),
                    )
                    if result.status == "resolved" and result.entity_id is not None:
                        confirmed[(league_id, raw, kickoff)] = result.entity_id
                    elif raw and (league_id, raw) not in seen_candidates:
                        enqueue_unknown_designation(
                            session,
                            reader,
                            source="the_odds_api",
                            kind="team",
                            scope={"sport": sport, "tournament": league_id},
                            value_kind="name",
                            raw_value=raw,
                            basis="Букмекерское обозначение ожидает решения владельца",
                            observed_at=datetime.now(UTC),
                            effective_at=kickoff,
                            facts={"tournament": tournament},
                        )
                        seen_candidates.add((league_id, raw))
        observations = project_odds_rows(
            events,
            odds_rows,
            specs,
            team_registry,
            registry_project_events=registry_project_events,
            confirmed_bookmaker_teams=confirmed,
            registry_snapshot_id=reader.snapshot_id,
        )
    else:
        observations = project_odds_rows(events, odds_rows, specs, team_registry)
    repository = CalendarRepository(session)
    return sum(repository.upsert_odds_observation(item) for item in observations)
