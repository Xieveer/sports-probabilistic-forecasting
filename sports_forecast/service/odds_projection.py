"""Однозначная проекция OddsStore в canonical event identity."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
from omegaconf import OmegaConf
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.identity.derived_event_matching import (
    DEFAULT_START_TOLERANCE,
    DerivedEventCandidate,
    match_derived_events,
)
from sports_forecast.identity.events import registry_event_reader_enabled
from sports_forecast.identity.installation import pin_installed_registry
from sports_forecast.service.db.models import CanonicalEvent
from sports_forecast.service.db.repository import CalendarRepository
from sports_forecast.service.registry_candidate_capture import enqueue_unknown_designation
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class OddsMarketColumns:
    """Колонки OddsStore, описывающие обязательные значения одного рынка."""

    market: str
    market_spec: str
    bookmaker: str
    value_columns: tuple[str, ...]
    provider_timestamp_column: str | None = None
    source_market_key: str = "h2h"


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
    calendar_candidates: Mapping[int, DerivedEventCandidate] | None = None,
    provider_candidate_resolver: Callable[[Any], DerivedEventCandidate] | None = None,
    market_supported: Callable[[Any, OddsMarketColumns], bool] | None = None,
    registry_snapshot_id: str | None = None,
) -> list[OddsObservationInput]:
    """Сопоставить линии по подтверждённым командам и kickoff с допуском 15 минут.

    Строки без фактического ``fetched_at``, времени начала, валидной линии или
    единственного взаимного соответствия игнорируются.
    """
    if odds_rows.empty:
        return []
    if (calendar_candidates is None) != (provider_candidate_resolver is None):
        raise ValueError("Derived odds matching требует обе коллекции обозначений")
    strict = calendar_candidates is not None
    if strict and market_supported is None:
        raise ValueError("Strict odds projection требует подтверждённое правило рынка")
    calendar_rows: list[DerivedEventCandidate] = []
    event_by_key: dict[str, Any] = {}
    for event in events:
        event_key = str(int(event.id))
        event_by_key[event_key] = event
        kickoff = _parse_timestamp(event.scheduled_at)
        if strict:
            assert calendar_candidates is not None
            candidate = calendar_candidates.get(int(event.id))
            if candidate is None:
                candidate = DerivedEventCandidate(
                    event_key,
                    None,
                    None,
                    None,
                    kickoff,
                    "unconfirmed_calendar_designation",
                )
        else:
            home = team_registry.resolve(event.home_participant or "")
            away = team_registry.resolve(event.away_participant or "")
            candidate = DerivedEventCandidate(
                event_key,
                str(getattr(event, "tournament", "")) or None,
                home or None,
                away or None,
                kickoff,
                None if home and away else "unconfirmed_calendar_team",
            )
        calendar_rows.append(candidate)

    provider_rows: list[DerivedEventCandidate] = []
    row_by_key: dict[str, Any] = {}
    for row_index, row in odds_rows.iterrows():
        row_key = str(row_index)
        if row_key in row_by_key:
            raise ValueError("Индекс строк OddsStore должен быть уникален")
        row_by_key[row_key] = row
        kickoff = _parse_timestamp(row.get("commence_time_utc"))
        if strict:
            assert provider_candidate_resolver is not None
            candidate = replace(provider_candidate_resolver(row), key=row_key, scheduled_at=kickoff)
        else:
            home = team_registry.resolve(str(row.get("home_team_norm") or ""))
            away = team_registry.resolve(str(row.get("away_team_norm") or ""))
            candidate = DerivedEventCandidate(
                row_key,
                str(getattr(events[0], "tournament", "")) if events else None,
                home or None,
                away or None,
                kickoff,
                None if home and away else "unconfirmed_provider_team",
            )
        provider_rows.append(candidate)

    match_result = match_derived_events(
        calendar_rows,
        provider_rows,
        tolerance=DEFAULT_START_TOLERANCE,
    )

    output: list[OddsObservationInput] = []
    for provider_key, event_key in match_result.provider_to_calendar.items():
        row = row_by_key[provider_key]
        event = event_by_key.get(event_key)
        if event is None:
            continue
        event_scheduled_at = _parse_timestamp(event.scheduled_at)
        if event_scheduled_at is None:
            continue
        for market in market_columns:
            if strict and market_supported is not None and not market_supported(row, market):
                logger.debug(
                    "OddsStore market unresolved row=%s market=%s reason=unconfirmed_market_rule",
                    row_key,
                    market.source_market_key,
                )
                continue
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
    for provider_key, reason in match_result.provider_reasons.items():
        logger.debug("OddsStore event match unresolved row=%s reason=%s", provider_key, reason)
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
            source_market_key=str(item.get("source_market_key") or "h2h"),
        )
        for item in policy.get("odds_markets", [])
    ]
    if registry_event_reader_enabled() and tournament.strip().lower() != "nhl":
        # Другие турниры пока сохраняют bridge-era strict lifecycle. Новый
        # словарный matcher включён для первого реального рынка NHL/Pinnacle.
        reader = pin_installed_registry(session)
        projects = {item.id: item for item in reader.event_snapshot.event_snapshot.events}
        calendar_candidates: dict[int, DerivedEventCandidate] = {}
        league_sports: set[tuple[str, str]] = set()
        for event in events:
            try:
                mapping = reader.get_event_mapping(int(event.id), session)
            except KeyError:
                continue
            project = projects.get(mapping.project_event_id or "")
            if mapping.status == "resolved" and project is not None:
                league_sports.add((project.tournament_id, project.sport))
                calendar_candidates[int(event.id)] = DerivedEventCandidate(
                    str(int(event.id)),
                    project.tournament_id,
                    project.home_team_id,
                    project.away_team_id,
                    _parse_timestamp(event.scheduled_at),
                )
        seen_candidates: set[tuple[str, str]] = set()

        def legacy_provider_candidate(row: Any) -> DerivedEventCandidate:
            kickoff = _parse_timestamp(row.get("commence_time_utc"))
            identities: set[tuple[str, str, str]] = set()
            for league_id, sport in league_sports:
                home_raw = str(row.get("home_team_norm") or "")
                away_raw = str(row.get("away_team_norm") or "")
                resolved = []
                for raw in (home_raw, away_raw):
                    result = reader.resolve_designation(
                        source="the_odds_api",
                        kind="team",
                        scope={"sport": sport, "tournament": league_id},
                        value_kind="name",
                        raw_value=raw,
                        at=kickoff.isoformat() if kickoff is not None else None,
                    )
                    resolved.append(result)
                    if result.status != "resolved" and raw and kickoff is not None:
                        candidate_key = (league_id, raw)
                        if candidate_key not in seen_candidates:
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
                            seen_candidates.add(candidate_key)
                if all(item.status == "resolved" for item in resolved):
                    identities.add((league_id, resolved[0].entity_id, resolved[1].entity_id))
            if len(identities) == 1:
                league_id, home_id, away_id = next(iter(identities))
                return DerivedEventCandidate("", league_id, home_id, away_id, kickoff)
            return DerivedEventCandidate("", None, None, None, kickoff, "unconfirmed_provider_team")

        observations = project_odds_rows(
            events,
            odds_rows,
            specs,
            team_registry,
            calendar_candidates=calendar_candidates,
            provider_candidate_resolver=legacy_provider_candidate,
            market_supported=lambda _row, _market: True,
            registry_snapshot_id=reader.snapshot_id,
        )
    elif registry_event_reader_enabled():
        reader = pin_installed_registry(session)
        nhl_calendar_candidates: dict[int, DerivedEventCandidate] = {}
        for event in events:
            scheduled = _parse_timestamp(event.scheduled_at)
            at = scheduled.isoformat() if scheduled is not None else None
            league = reader.resolve_designation(
                source=str(event.source),
                kind="tournament",
                scope={"sport": str(event.sport)},
                value_kind="name",
                raw_value=str(event.tournament),
                at=at,
            )
            scope = {"sport": str(event.sport), "tournament": league.entity_id or ""}
            home = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(event.home_participant or ""),
                at=at,
            )
            away = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(event.away_participant or ""),
                at=at,
            )
            reason = None
            if league.status != "resolved":
                reason = "unconfirmed_calendar_tournament"
            elif home.status != "resolved" or away.status != "resolved":
                reason = "unconfirmed_calendar_team"
            nhl_calendar_candidates[int(event.id)] = DerivedEventCandidate(
                key=str(int(event.id)),
                tournament_id=league.entity_id,
                home_team_id=home.entity_id,
                away_team_id=away.entity_id,
                scheduled_at=scheduled,
                unresolved_reason=reason,
            )

        book_cfg = load_bookmaker_config("the_odds_api")
        sport_key = (
            str(OmegaConf.select(book_cfg, f"bookmaker.sport_keys.{tournament}") or "")
            if book_cfg is not None
            else ""
        )
        sports = {str(event.sport) for event in events}
        provider_league_ids: dict[Any, str | None] = {}
        seen_league_candidates: set[str] = set()
        nhl_seen_candidates: set[tuple[str, str]] = set()
        seen_market_candidates: set[tuple[str, str, str]] = set()

        def provider_candidate(row: Any) -> DerivedEventCandidate:
            kickoff = _parse_timestamp(row.get("commence_time_utc"))
            instant = kickoff.isoformat() if kickoff is not None else None
            sport = next(iter(sports)) if len(sports) == 1 else ""
            league = reader.resolve_designation(
                source="the_odds_api",
                kind="tournament",
                scope={"sport": sport},
                value_kind="external_id",
                raw_value=sport_key,
                at=instant,
            )
            league_id = league.entity_id if league.status == "resolved" else None
            provider_league_ids[row.name] = league_id
            if (
                league_id is None
                and kickoff is not None
                and sport_key not in seen_league_candidates
            ):
                enqueue_unknown_designation(
                    session,
                    reader,
                    source="the_odds_api",
                    kind="tournament",
                    scope={"sport": sport},
                    value_kind="external_id",
                    raw_value=sport_key,
                    basis="Источник odds впервые встретил турнир",
                    observed_at=datetime.now(UTC),
                    effective_at=kickoff,
                    facts={"sport": sport},
                )
                seen_league_candidates.add(sport_key)
            home_id = away_id = None
            reason = None
            if league_id is None:
                reason = "unconfirmed_provider_tournament"
            else:
                scope = {"sport": sport, "tournament": league_id}
                raw_teams = (
                    str(row.get("home_team_norm") or ""),
                    str(row.get("away_team_norm") or ""),
                )
                resolutions = []
                for raw in raw_teams:
                    result = reader.resolve_designation(
                        source="the_odds_api",
                        kind="team",
                        scope=scope,
                        value_kind="name",
                        raw_value=raw,
                        at=instant,
                    )
                    resolutions.append(result)
                    if result.status != "resolved" and raw and kickoff is not None:
                        candidate_key = ("team", raw)
                        if candidate_key not in nhl_seen_candidates:
                            enqueue_unknown_designation(
                                session,
                                reader,
                                source="the_odds_api",
                                kind="team",
                                scope=scope,
                                value_kind="name",
                                raw_value=raw,
                                basis="Букмекерское обозначение ожидает решения владельца",
                                observed_at=datetime.now(UTC),
                                effective_at=kickoff,
                                facts={"tournament": tournament, "sport_key": sport_key},
                            )
                            nhl_seen_candidates.add(candidate_key)
                home_id = resolutions[0].entity_id if resolutions[0].status == "resolved" else None
                away_id = resolutions[1].entity_id if resolutions[1].status == "resolved" else None
                if home_id is None or away_id is None:
                    reason = "unconfirmed_provider_team"
            return DerivedEventCandidate(
                key="",
                tournament_id=league_id,
                home_team_id=home_id,
                away_team_id=away_id,
                scheduled_at=kickoff,
                unresolved_reason=reason,
            )

        def market_supported(row: Any, spec: OddsMarketColumns) -> bool:
            kickoff = _parse_timestamp(row.get("commence_time_utc"))
            sport = next(iter(sports)) if len(sports) == 1 else ""
            if kickoff is None or not sport or not sport_key:
                return False
            league_id = provider_league_ids.get(row.name)
            if league_id is None:
                return False
            resolution = reader.resolve_market(
                source="the_odds_api",
                sport=sport,
                tournament_id=league_id,
                bookmaker=spec.bookmaker,
                raw_market_key=spec.source_market_key,
                at=kickoff.isoformat(),
            )
            if resolution.status != "resolved" or resolution.entity_id is None:
                market_candidate_key = (league_id, spec.bookmaker, spec.source_market_key)
                if market_candidate_key not in seen_market_candidates:
                    enqueue_unknown_designation(
                        session,
                        reader,
                        source="the_odds_api",
                        kind="market",
                        scope={
                            "sport": sport,
                            "tournament": league_id,
                            "bookmaker": spec.bookmaker,
                        },
                        value_kind="name",
                        raw_value=spec.source_market_key,
                        basis="Рынок букмекера ожидает решения владельца",
                        observed_at=datetime.now(UTC),
                        effective_at=kickoff,
                        facts={"tournament": tournament, "market_spec": spec.market_spec},
                    )
                    seen_market_candidates.add(market_candidate_key)
                return False
            try:
                market_entity = reader.get_entity(resolution.entity_id)
                rule = reader.get_market_rule(resolution.entity_id)
            except KeyError:
                return False
            return (
                market_entity.project_name == spec.market_spec
                and rule.period == "game"
                and rule.overtime
                and rule.shootout
                and not rule.draw
                and set(rule.valid_outcome_keys) == {"home_win", "away_win"}
            )

        observations = project_odds_rows(
            events,
            odds_rows,
            specs,
            team_registry,
            calendar_candidates=nhl_calendar_candidates,
            provider_candidate_resolver=provider_candidate,
            market_supported=market_supported,
            registry_snapshot_id=reader.snapshot_id,
        )
    else:
        observations = project_odds_rows(events, odds_rows, specs, team_registry)
    repository = CalendarRepository(session)
    return sum(repository.upsert_odds_observation(item) for item in observations)
