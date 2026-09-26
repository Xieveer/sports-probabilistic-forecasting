"""Пакетное получение и строгая проекция будущих NHL odds на календарь."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
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
from sports_forecast.service.db.models import CanonicalEvent, OddsAcquisitionAttempt
from sports_forecast.service.db.repository import CalendarRepository
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
) -> dict[str, float] | None:
    """Принять лишь точную двухисходную пару участников с decimal prices."""
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return None
    expected = {registry.resolve(home_team): "home", registry.resolve(away_team): "away"}
    if not all(expected.values()) or len(expected) != 2:
        return None
    result: dict[str, float] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            return None
        normalized = registry.resolve(str(outcome.get("name") or ""))
        side = expected.get(normalized)
        if side is None or side in result:
            return None
        try:
            price = float(outcome.get("price"))
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
) -> tuple[list[FutureOddsObservation], dict[str, int]]:
    """Сопоставить source batch по командам и точному UTC kickoff.

    Отсутствующая линия остаётся missing. Дефектные/трёхисходные рынки,
    неизвестные участники и неоднозначные события не создают наблюдение.
    """
    if not isinstance(payload, list):
        raise ValueError("Odds API batch должен быть списком событий")
    event_index: dict[tuple[str, str, datetime], list[Any]] = defaultdict(list)
    for event in events:
        kickoff = _utc(event.scheduled_at)
        home = team_registry.resolve(str(event.home_participant or ""))
        away = team_registry.resolve(str(event.away_participant or ""))
        if event.status == "scheduled" and home and away and home != away:
            event_index[(home, away, kickoff)].append(event)

    provider_matches: dict[tuple[str, str, datetime], int] = defaultdict(int)
    for item in payload:
        if not isinstance(item, dict):
            continue
        kickoff = _parse_time(item.get("commence_time"))
        home = team_registry.resolve(str(item.get("home_team") or ""))
        away = team_registry.resolve(str(item.get("away_team") or ""))
        if kickoff is not None and home and away and (home, away, kickoff) in event_index:
            provider_matches[(home, away, kickoff)] += 1

    observations: list[FutureOddsObservation] = []
    matched_ids: set[int] = set()
    rejected = 0
    for provider_event in payload:
        if not isinstance(provider_event, dict):
            rejected += 1
            continue
        provider_id = str(provider_event.get("id") or "").strip()
        kickoff = _parse_time(provider_event.get("commence_time"))
        home_team = str(provider_event.get("home_team") or "").strip()
        away_team = str(provider_event.get("away_team") or "").strip()
        home = team_registry.resolve(home_team)
        away = team_registry.resolve(away_team)
        if not provider_id or kickoff is None or not home or not away:
            rejected += 1
            continue
        candidates = event_index.get((home, away, kickoff), [])
        if not candidates:
            continue
        identity = (home, away, kickoff)
        if len(candidates) != 1 or provider_matches[identity] != 1:
            rejected += 1
            continue
        event = candidates[0]
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
            raw_observed_at = bookmaker.get("last_update")
        observed_at = _parse_time(raw_observed_at)
        values = _outcome_prices(
            market.get("outcomes"),
            home_team=home_team,
            away_team=away_team,
            registry=team_registry,
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
            )
        )
        matched_ids.add(int(event.id))

    counts = {
        "provider_events": len(payload),
        "matched": len(matched_ids),
        "missing": max(0, len({int(event.id) for event in events}) - len(matched_ids)),
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
            OddsAcquisitionAttempt.run_id == run_id,
            OddsAcquisitionAttempt.provider == _SOURCE,
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
    events = list(
        session.scalars(
            select(CanonicalEvent).where(
                CanonicalEvent.tournament == "nhl",
                CanonicalEvent.status == "scheduled",
                CanonicalEvent.scheduled_at >= reference.replace(tzinfo=None),
                CanonicalEvent.scheduled_at <= (reference + horizon).replace(tzinfo=None),
            )
        ).all()
    )
    registry = team_registry or load_nhl_team_name_registry()
    client = provider
    quota = OddsApiQuotaSnapshot(None, None)
    retrieved_at = _utc(clock())
    window_from = min((_utc(event.scheduled_at) for event in events), default=None)
    window_to = max((_utc(event.scheduled_at) for event in events), default=None)
    if window_from is not None and window_to is not None and window_to <= window_from:
        window_to = window_from + timedelta(seconds=1)
    failure_code: str | None = None
    observations: list[FutureOddsObservation] = []
    counts = {"provider_events": 0, "matched": 0, "missing": len(events), "rejected": 0}
    try:
        if events:
            if client is None:
                client = OddsApiClient(max_real_http_requests=1, max_retries=0)
            if window_from is None or window_to is None:
                raise ValueError("Не удалось вычислить временное окно odds batch")
            payload = client.fetch_future_nhl_odds(
                commence_time_from=window_from, commence_time_to=window_to, use_cache=False
            )
            retrieved_at = _utc(clock())
            quota = client.last_quota()
            observations, counts = parse_nhl_future_odds(
                events, payload, registry, retrieved_at=retrieved_at
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
        counts = {"provider_events": 0, "matched": 0, "missing": len(events), "rejected": 0}
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
