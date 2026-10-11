"""Пакетное получение и строгая проекция будущих NHL odds на календарь."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.data.providers.odds.client import (
    OddsApiClient,
    OddsApiQuotaSnapshot,
    QuotaBudgetError,
)
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.identity.derived_event_matching import (
    DEFAULT_START_TOLERANCE,
    DerivedEventCandidate,
    match_derived_events,
)
from sports_forecast.identity.events import registry_event_reader_enabled
from sports_forecast.identity.installation import InstalledRegistryReader, pin_installed_registry
from sports_forecast.service.db.models import CanonicalEvent, OddsAcquisitionAttempt
from sports_forecast.service.db.repository import CalendarRepository
from sports_forecast.service.registry_candidate_capture import enqueue_unknown_designation
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_SOURCE = "the_odds_api_v4"
_PROVIDER_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


class FutureOddsProvider(Protocol):
    """Минимальная граница внешнего источника для Data Cycle и fake provider."""

    def fetch_future_nhl_odds(
        self, *, commence_time_from: datetime, commence_time_to: datetime, use_cache: bool = False
    ) -> dict[str, Any] | list[Any]: ...

    def last_quota(self) -> OddsApiQuotaSnapshot: ...


@dataclass(frozen=True)
class FutureOddsObservation:
    """Валидированная линия с раздельным временем источника и получения."""

    canonical_event_id: int
    market: str
    market_spec: str
    bookmaker: str
    event_scheduled_at: datetime
    event_home_participant: str
    event_away_participant: str
    observed_at: datetime
    observed_at_source: str
    retrieved_at: datetime
    provider_event_id: str
    values: dict[str, float]
    source: str = _SOURCE
    registry_snapshot_id: str | None = None


@dataclass(frozen=True)
class FutureOddsAttempt:
    """Безопасное summary одной попытки сбора без сырых provider payloads."""

    run_id: str
    tournament: str
    provider: str
    status: str
    failure_code: str | None
    retrieved_at: datetime
    window_from: datetime | None = None
    window_to: datetime | None = None
    provider_events: int = 0
    matched_events: int = 0
    missing_events: int = 0
    rejected_events: int = 0
    requests_remaining: int | None = None
    requests_used: int | None = None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _outcome_prices(
    outcomes: object,
    *,
    home_team: str,
    away_team: str,
    registry: TeamNameRegistry,
    expected_team_ids: tuple[str, str] | None = None,
    resolve_team_id: Callable[[str, datetime], str | None] | None = None,
    at: datetime | None = None,
) -> dict[str, float] | None:
    """Принять лишь точную двухисходную пару участников с decimal prices."""
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return None
    if expected_team_ids is not None:
        if resolve_team_id is None or at is None:
            raise ValueError("Strict outcome matching требует подтверждённый team resolver")
        home_id, away_id = expected_team_ids
        if (
            home_id == away_id
            or resolve_team_id(home_team, at) != home_id
            or resolve_team_id(away_team, at) != away_id
        ):
            return None
        expected = {home_id: "home", away_id: "away"}
    else:
        expected = {registry.resolve(home_team): "home", registry.resolve(away_team): "away"}
    if not all(expected.values()) or len(expected) != 2:
        return None
    result: dict[str, float] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            return None
        raw_name = str(outcome.get("name") or "")
        normalized = (
            resolve_team_id(raw_name, at)
            if expected_team_ids is not None and resolve_team_id is not None and at is not None
            else registry.resolve(raw_name)
        )
        side = expected.get(normalized)
        if side is None or side in result:
            return None
        try:
            raw_price = outcome.get("price")
            if raw_price is None:
                return None
            price = float(raw_price)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price) or price <= 1.0:
            return None
        result[side] = price
    return result if set(result) == {"home", "away"} else None


def parse_nhl_future_odds(
    events: Sequence[Any],
    payload: object,
    team_registry: TeamNameRegistry,
    *,
    retrieved_at: datetime,
    calendar_candidates: Mapping[int, DerivedEventCandidate] | None = None,
    provider_candidate_resolver: Callable[[dict[str, Any]], DerivedEventCandidate] | None = None,
    market_supported: Callable[[dict[str, Any]], bool] | None = None,
    confirmed_team_id: Callable[[str, datetime], str | None] | None = None,
    registry_snapshot_id: str | None = None,
    eligible_event_ids: set[int] | None = None,
) -> tuple[list[FutureOddsObservation], dict[str, int]]:
    """Сопоставить source batch по подтверждённым сторонам и kickoff с допуском 15 минут.

    Отсутствующая линия остаётся missing. Дефектные/трёхисходные рынки,
    неизвестные участники и неоднозначные события не создают наблюдение.
    """
    if not isinstance(payload, list):
        raise ValueError("Odds API batch должен быть списком событий")
    if (calendar_candidates is None) != (provider_candidate_resolver is None):
        raise ValueError("Derived future odds matching требует обе коллекции обозначений")
    strict = calendar_candidates is not None
    if strict and confirmed_team_id is None:
        raise ValueError("Strict future odds требует подтверждённые team IDs для outcomes")
    eligible_events = [
        event
        for event in events
        if event.status == "scheduled"
        and (eligible_event_ids is None or int(event.id) in eligible_event_ids)
    ]
    eligible_ids = {int(event.id) for event in eligible_events}
    event_by_key: dict[str, Any] = {}
    resolved_calendar_candidates: list[DerivedEventCandidate] = []
    for event in events:
        key = str(int(event.id))
        event_by_key[key] = event
        if event.status != "scheduled":
            continue
        if strict:
            assert calendar_candidates is not None
            candidate = calendar_candidates.get(int(event.id))
            if candidate is None:
                candidate = DerivedEventCandidate(
                    key=key,
                    tournament_id=None,
                    home_team_id=None,
                    away_team_id=None,
                    scheduled_at=_utc(event.scheduled_at),
                    unresolved_reason="unconfirmed_calendar_designation",
                )
        else:
            home = team_registry.resolve(str(event.home_participant or ""))
            away = team_registry.resolve(str(event.away_participant or ""))
            candidate = DerivedEventCandidate(
                key=key,
                tournament_id="nhl",
                home_team_id=home or None,
                away_team_id=away or None,
                scheduled_at=_utc(event.scheduled_at),
                unresolved_reason=None if home and away else "unconfirmed_calendar_team",
            )
        resolved_calendar_candidates.append(candidate)

    provider_rows_by_id: dict[str, list[dict[str, Any]]] = {}
    invalid_provider_count = 0
    for item in payload:
        if not isinstance(item, dict):
            invalid_provider_count += 1
            continue
        provider_id = str(item.get("id") or "").strip()
        if not provider_id:
            invalid_provider_count += 1
            continue
        provider_rows_by_id.setdefault(provider_id, []).append(item)
    unique_provider_events: dict[str, dict[str, Any]] = {}
    conflicting_provider_ids: set[str] = set()
    for provider_id, rows in provider_rows_by_id.items():
        usable_rows = [
            row
            for row in rows
            if _parse_time(row.get("commence_time")) is not None
            and str(row.get("home_team") or "").strip()
            and str(row.get("away_team") or "").strip()
        ]
        distinct_usable = {
            json.dumps(row, sort_keys=True, separators=(",", ":")): row for row in usable_rows
        }
        if len(distinct_usable) > 1:
            conflicting_provider_ids.add(provider_id)
        elif distinct_usable:
            unique_provider_events[provider_id] = next(iter(distinct_usable.values()))
        elif rows:
            invalid_provider_count += 1
    provider_candidates: list[DerivedEventCandidate] = []
    provider_by_key: dict[str, dict[str, Any]] = {}
    for key, item in unique_provider_events.items():
        if key in conflicting_provider_ids:
            continue
        provider_by_key[key] = item
        if strict:
            assert provider_candidate_resolver is not None
            resolved = provider_candidate_resolver(item)
            candidate = DerivedEventCandidate(
                key=key,
                tournament_id=resolved.tournament_id,
                home_team_id=resolved.home_team_id,
                away_team_id=resolved.away_team_id,
                scheduled_at=_parse_time(item.get("commence_time")),
                unresolved_reason=resolved.unresolved_reason,
            )
        else:
            home = team_registry.resolve(str(item.get("home_team") or ""))
            away = team_registry.resolve(str(item.get("away_team") or ""))
            candidate = DerivedEventCandidate(
                key=key,
                tournament_id="nhl",
                home_team_id=home or None,
                away_team_id=away or None,
                scheduled_at=_parse_time(item.get("commence_time")),
                unresolved_reason=None if home and away else "unconfirmed_provider_team",
            )
        provider_candidates.append(candidate)
    match_result = match_derived_events(
        resolved_calendar_candidates,
        provider_candidates,
        tolerance=DEFAULT_START_TOLERANCE,
    )

    observations: list[FutureOddsObservation] = []
    matched_ids: set[int] = set()
    rejected = invalid_provider_count + len(conflicting_provider_ids)
    for provider_id, provider_event in provider_by_key.items():
        provider_id = str(provider_event.get("id") or "").strip()
        provider_kickoff = _parse_time(provider_event.get("commence_time"))
        home_team = str(provider_event.get("home_team") or "").strip()
        away_team = str(provider_event.get("away_team") or "").strip()
        if not provider_id or provider_kickoff is None or not home_team or not away_team:
            rejected += 1
            continue
        event_key = match_result.provider_to_calendar.get(provider_id)
        if event_key is None:
            reason = match_result.provider_reasons.get(provider_id, "no_matching_event")
            if reason == "ambiguous":
                rejected += 1
            logger.debug(
                "future odds event match unresolved provider_event_id=%s reason=%s",
                provider_id,
                reason,
            )
            continue
        event = event_by_key[event_key]
        if int(event.id) not in eligible_ids:
            continue
        bookmakers = provider_event.get("bookmakers")
        pinnacle_bookmakers = [
            item
            for item in bookmakers or []
            if isinstance(item, dict) and item.get("key") == "pinnacle"
        ]
        if len(pinnacle_bookmakers) > 1:
            rejected += 1
            continue
        bookmaker = pinnacle_bookmakers[0] if pinnacle_bookmakers else None
        markets = bookmaker.get("markets") if isinstance(bookmaker, dict) else None
        h2h_markets = [
            item for item in markets or [] if isinstance(item, dict) and item.get("key") == "h2h"
        ]
        if len(h2h_markets) > 1:
            rejected += 1
            continue
        market = h2h_markets[0] if h2h_markets else None
        if not isinstance(market, dict):
            continue
        if strict and (market_supported is None or not market_supported(provider_event)):
            rejected += 1
            logger.debug(
                "future odds market unresolved provider_event_id=%s reason=unconfirmed_market_rule",
                provider_id,
            )
            continue
        timestamp_source = "market.last_update"
        raw_observed_at = market.get("last_update")
        if raw_observed_at is None:
            single_h2h_market = (
                isinstance(markets, list)
                and len(markets) == 1
                and isinstance(markets[0], dict)
                and markets[0].get("key") == "h2h"
            )
            if not single_h2h_market:
                rejected += 1
                continue
            timestamp_source = "bookmaker.last_update"
            raw_observed_at = bookmaker.get("last_update") if isinstance(bookmaker, dict) else None
        observed_at = _parse_time(raw_observed_at)
        values = _outcome_prices(
            market.get("outcomes"),
            home_team=home_team,
            away_team=away_team,
            registry=team_registry,
            expected_team_ids=(
                (
                    calendar_candidates[int(event.id)].home_team_id,
                    calendar_candidates[int(event.id)].away_team_id,
                )
                if calendar_candidates is not None
                and int(event.id) in calendar_candidates
                and calendar_candidates[int(event.id)].home_team_id is not None
                and calendar_candidates[int(event.id)].away_team_id is not None
                else None
            ),
            resolve_team_id=confirmed_team_id,
            at=provider_kickoff,
        )
        if (
            observed_at is None
            or observed_at > _utc(retrieved_at) + _PROVIDER_CLOCK_SKEW_TOLERANCE
            or values is None
        ):
            rejected += 1
            continue
        observations.append(
            FutureOddsObservation(
                canonical_event_id=int(event.id),
                market="winner",
                market_spec="winner_withOT",
                bookmaker="pinnacle",
                event_scheduled_at=_utc(event.scheduled_at),
                event_home_participant=str(event.home_participant),
                event_away_participant=str(event.away_participant),
                observed_at=observed_at,
                observed_at_source=timestamp_source,
                retrieved_at=_utc(retrieved_at),
                provider_event_id=provider_id,
                values=values,
                registry_snapshot_id=registry_snapshot_id,
            )
        )
        matched_ids.add(int(event.id))

    counts = {
        "provider_events": len(payload),
        "matched": len(matched_ids),
        "missing": max(0, len(eligible_ids) - len(matched_ids)),
        "rejected": rejected,
    }
    return observations, counts


def run_nhl_future_odds_batch(
    session: Session,
    *,
    run_id: str,
    now: datetime,
    provider: FutureOddsProvider | None = None,
    team_registry: TeamNameRegistry | None = None,
    horizon: timedelta = timedelta(days=30),
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FutureOddsAttempt:
    """Выполнить не более одного NHL batch и сохранить observation или failure.

    Внутренняя квота клиента равна одному реальному GET; cache отключён для
    freshness. Ошибки источника сохраняются безопасным кодом, не raw exception.
    """
    reference = _utc(now)
    existing_attempt = session.scalar(
        select(OddsAcquisitionAttempt).where(
            OddsAcquisitionAttempt.__table__.c.run_id == run_id,
            OddsAcquisitionAttempt.__table__.c.provider == _SOURCE,
        )
    )
    if existing_attempt is not None:
        return FutureOddsAttempt(
            run_id=existing_attempt.run_id,
            tournament=existing_attempt.tournament,
            provider=existing_attempt.provider,
            status=existing_attempt.status,
            failure_code=existing_attempt.failure_code,
            retrieved_at=_utc(existing_attempt.retrieved_at),
            window_from=_utc(existing_attempt.window_from)
            if existing_attempt.window_from is not None
            else None,
            window_to=_utc(existing_attempt.window_to)
            if existing_attempt.window_to is not None
            else None,
            provider_events=existing_attempt.provider_events,
            matched_events=existing_attempt.matched_events,
            missing_events=existing_attempt.missing_events,
            rejected_events=existing_attempt.rejected_events,
            requests_remaining=existing_attempt.requests_remaining,
            requests_used=existing_attempt.requests_used,
        )
    target_events = list(
        session.scalars(
            select(CanonicalEvent).where(
                CanonicalEvent.__table__.c.tournament == "nhl",
                CanonicalEvent.__table__.c.status == "scheduled",
                CanonicalEvent.__table__.c.scheduled_at >= reference.replace(tzinfo=None),
                CanonicalEvent.__table__.c.scheduled_at
                <= (reference + horizon).replace(tzinfo=None),
            )
        ).all()
    )
    tolerance = DEFAULT_START_TOLERANCE
    events = list(
        session.scalars(
            select(CanonicalEvent).where(
                CanonicalEvent.__table__.c.tournament == "nhl",
                CanonicalEvent.__table__.c.status == "scheduled",
                CanonicalEvent.__table__.c.scheduled_at
                >= (reference - tolerance).replace(tzinfo=None),
                CanonicalEvent.__table__.c.scheduled_at
                <= (reference + horizon + tolerance).replace(tzinfo=None),
            )
        ).all()
    )
    target_event_ids = {int(event.id) for event in target_events}
    calendar_candidates: dict[int, DerivedEventCandidate] | None = None
    registry_snapshot_id: str | None = None
    provider_candidate_resolver: Callable[[dict[str, Any]], DerivedEventCandidate] | None = None
    market_supported: Callable[[dict[str, Any]], bool] | None = None
    confirmed_team_id: Callable[[str, datetime], str | None] | None = None
    reader: InstalledRegistryReader | None = None
    if registry_event_reader_enabled():
        reader = pin_installed_registry(session)
        registry_snapshot_id = reader.snapshot_id
        calendar_candidates = {}
        sports = {str(event.sport) for event in events}
        for event in events:
            at = _utc(event.scheduled_at)
            league = reader.resolve_designation(
                source=str(event.source),
                kind="tournament",
                scope={"sport": str(event.sport)},
                value_kind="name",
                raw_value=str(event.tournament),
                at=at.isoformat(),
            )
            scope = {"sport": str(event.sport), "tournament": league.entity_id or ""}
            home = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(event.home_participant or ""),
                at=at.isoformat(),
            )
            away = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(event.away_participant or ""),
                at=at.isoformat(),
            )
            reason = None
            if league.status != "resolved":
                reason = "unconfirmed_calendar_tournament"
            elif home.status != "resolved" or away.status != "resolved":
                reason = "unconfirmed_calendar_team"
            calendar_candidates[int(event.id)] = DerivedEventCandidate(
                key=str(int(event.id)),
                tournament_id=league.entity_id,
                home_team_id=home.entity_id,
                away_team_id=away.entity_id,
                scheduled_at=at,
                unresolved_reason=reason,
            )

        def resolve_confirmed_team(raw: str, at: datetime) -> str | None:
            if len(sports) != 1 or reader is None:
                return None
            sport = next(iter(sports))
            tournament = reader.resolve_designation(
                source="the_odds_api",
                kind="tournament",
                scope={"sport": sport},
                value_kind="external_id",
                raw_value="icehockey_nhl",
                at=at.isoformat(),
            )
            if tournament.status != "resolved" or tournament.entity_id is None:
                return None
            team = reader.resolve_designation(
                source="the_odds_api",
                kind="team",
                scope={"sport": sport, "tournament": tournament.entity_id},
                value_kind="name",
                raw_value=raw,
                at=at.isoformat(),
            )
            return team.entity_id if team.status == "resolved" else None

        confirmed_team_id = resolve_confirmed_team

        def resolve_provider_identity(item: dict[str, Any]) -> DerivedEventCandidate:
            kickoff = _parse_time(item.get("commence_time"))
            sport = next(iter(sports)) if len(sports) == 1 else ""
            instant = kickoff.isoformat() if kickoff is not None else None
            league = reader.resolve_designation(
                source="the_odds_api",
                kind="tournament",
                scope={"sport": sport},
                value_kind="external_id",
                raw_value="icehockey_nhl",
                at=instant,
            )
            scope = {"sport": sport, "tournament": league.entity_id or ""}
            home = reader.resolve_designation(
                source="the_odds_api",
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(item.get("home_team") or ""),
                at=instant,
            )
            away = reader.resolve_designation(
                source="the_odds_api",
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=str(item.get("away_team") or ""),
                at=instant,
            )
            reason = None
            if len(sports) != 1 or league.status != "resolved":
                reason = "unconfirmed_provider_tournament"
            elif home.status != "resolved" or away.status != "resolved":
                reason = "unconfirmed_provider_team"
            return DerivedEventCandidate(
                key=str(item.get("id") or ""),
                tournament_id=league.entity_id,
                home_team_id=home.entity_id,
                away_team_id=away.entity_id,
                scheduled_at=kickoff,
                unresolved_reason=reason,
            )

        provider_candidate_resolver = resolve_provider_identity

        def confirm_market_rule(item: dict[str, Any]) -> bool:
            if reader is None or len(sports) != 1:
                return False
            kickoff = _parse_time(item.get("commence_time"))
            if kickoff is None:
                return False
            league = reader.resolve_designation(
                source="the_odds_api",
                kind="tournament",
                scope={"sport": next(iter(sports))},
                value_kind="external_id",
                raw_value="icehockey_nhl",
                at=kickoff.isoformat(),
            )
            if league.status != "resolved" or league.entity_id is None:
                return False
            market = reader.resolve_market(
                source="the_odds_api",
                sport=next(iter(sports)),
                tournament_id=league.entity_id,
                bookmaker="pinnacle",
                raw_market_key="h2h",
                at=kickoff.isoformat(),
            )
            if market.status != "resolved" or market.entity_id is None:
                return False
            try:
                rule = reader.get_market_rule(market.entity_id)
            except KeyError:
                return False
            return (
                rule.period == "game"
                and rule.overtime
                and rule.shootout
                and not rule.draw
                and set(rule.valid_outcome_keys) == {"home_win", "away_win"}
                and reader.get_entity(market.entity_id).project_name == "winner_withOT"
            )

        market_supported = confirm_market_rule
    registry = team_registry or load_nhl_team_name_registry(strict_mode=reader is not None)
    client = provider
    quota = OddsApiQuotaSnapshot(None, None)
    retrieved_at = _utc(clock())
    window_from = min((_utc(event.scheduled_at) for event in target_events), default=None)
    window_to = max((_utc(event.scheduled_at) for event in target_events), default=None)
    if window_from is not None and window_to is not None and window_to <= window_from:
        window_to = window_from + timedelta(seconds=1)
    if window_from is not None and window_to is not None:
        window_from -= tolerance
        window_to += tolerance
    failure_code: str | None = None
    observations: list[FutureOddsObservation] = []
    counts = {
        "provider_events": 0,
        "matched": 0,
        "missing": len(target_events),
        "rejected": 0,
    }
    try:
        if target_events:
            if client is None:
                client = OddsApiClient(max_real_http_requests=1, max_retries=0)
            if window_from is None or window_to is None:
                raise ValueError("Не удалось вычислить временное окно odds batch")
            payload = client.fetch_future_nhl_odds(
                commence_time_from=window_from, commence_time_to=window_to, use_cache=False
            )
            retrieved_at = _utc(clock())
            quota = client.last_quota()
            if reader is not None and isinstance(payload, list) and len(sports) == 1:
                sport = next(iter(sports))
                seen_candidates: set[tuple[str, str]] = set()
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    item_kickoff = _parse_time(item.get("commence_time"))
                    if item_kickoff is None:
                        continue
                    league = reader.resolve_designation(
                        source="the_odds_api",
                        kind="tournament",
                        scope={"sport": sport},
                        value_kind="external_id",
                        raw_value="icehockey_nhl",
                        at=item_kickoff.isoformat(),
                    )
                    if league.status != "resolved" or league.entity_id is None:
                        candidate_key = ("tournament", "icehockey_nhl")
                        if candidate_key not in seen_candidates:
                            enqueue_unknown_designation(
                                session,
                                reader,
                                source="the_odds_api",
                                kind="tournament",
                                scope={"sport": sport},
                                value_kind="external_id",
                                raw_value="icehockey_nhl",
                                basis="Источник odds впервые встретил турнир",
                                observed_at=retrieved_at,
                                effective_at=item_kickoff,
                                facts={"sport": sport},
                            )
                            seen_candidates.add(candidate_key)
                        continue
                    scope = {"sport": sport, "tournament": league.entity_id}
                    market_scope = {**scope, "bookmaker": "pinnacle"}
                    market = reader.resolve_market(
                        source="the_odds_api",
                        sport=sport,
                        tournament_id=league.entity_id,
                        bookmaker="pinnacle",
                        raw_market_key="h2h",
                        at=item_kickoff.isoformat(),
                    )
                    market_key = ("market", f"{league.entity_id}:pinnacle:h2h")
                    if market.status != "resolved" and market_key not in seen_candidates:
                        enqueue_unknown_designation(
                            session,
                            reader,
                            source="the_odds_api",
                            kind="market",
                            scope=market_scope,
                            value_kind="name",
                            raw_value="h2h",
                            basis="Рынок букмекера ожидает решения владельца",
                            observed_at=retrieved_at,
                            effective_at=item_kickoff,
                            facts={"sport_key": "icehockey_nhl", "bookmaker": "pinnacle"},
                        )
                        seen_candidates.add(market_key)
                    for raw in (str(item.get("home_team") or ""), str(item.get("away_team") or "")):
                        team = reader.resolve_designation(
                            source="the_odds_api",
                            kind="team",
                            scope=scope,
                            value_kind="name",
                            raw_value=raw,
                            at=item_kickoff.isoformat(),
                        )
                        if (
                            team.status != "resolved"
                            and raw
                            and ("team", raw) not in seen_candidates
                        ):
                            enqueue_unknown_designation(
                                session,
                                reader,
                                source="the_odds_api",
                                kind="team",
                                scope=scope,
                                value_kind="name",
                                raw_value=raw,
                                basis="Источник odds впервые встретил команду",
                                observed_at=retrieved_at,
                                effective_at=item_kickoff,
                                facts={"sport_key": "icehockey_nhl"},
                            )
                            seen_candidates.add(("team", raw))
            observations, counts = parse_nhl_future_odds(
                events,
                payload,
                registry,
                retrieved_at=retrieved_at,
                calendar_candidates=calendar_candidates,
                provider_candidate_resolver=provider_candidate_resolver,
                market_supported=market_supported,
                confirmed_team_id=confirmed_team_id,
                registry_snapshot_id=registry_snapshot_id,
                eligible_event_ids=target_event_ids,
            )
            repository = CalendarRepository(session)
            for observation in observations:
                repository.upsert_odds_observation(observation)
    except QuotaBudgetError:
        failure_code = "quota_exhausted"
    except requests.HTTPError as exc:
        retrieved_at = _utc(clock())
        failure_code = (
            "quota_exhausted"
            if exc.response is not None and exc.response.status_code == 429
            else "provider_unavailable"
        )
    except requests.RequestException:
        retrieved_at = _utc(clock())
        failure_code = "provider_unavailable"
    except ValueError:
        retrieved_at = _utc(clock())
        failure_code = "provider_not_configured" if client is None else "provider_response_invalid"
    except TypeError:
        retrieved_at = _utc(clock())
        failure_code = "provider_response_invalid"
    if client is not None:
        quota = client.last_quota()
    if failure_code:
        status = "failed"
        counts = {
            "provider_events": 0,
            "matched": 0,
            "missing": len(target_events),
            "rejected": 0,
        }
        logger.warning(
            "NHL future odds acquisition failed: run_id=%s code=%s", run_id, failure_code
        )
    else:
        status = "partial_success" if counts["rejected"] else "success"
    attempt = FutureOddsAttempt(
        run_id=run_id,
        tournament="nhl",
        provider=_SOURCE,
        status=status,
        failure_code=failure_code,
        retrieved_at=retrieved_at,
        window_from=window_from,
        window_to=window_to,
        provider_events=counts["provider_events"],
        matched_events=counts["matched"],
        missing_events=counts["missing"],
        rejected_events=counts["rejected"],
        requests_remaining=quota.requests_remaining,
        requests_used=quota.requests_used,
    )
    CalendarRepository(session).record_odds_attempt(attempt)
    return attempt
