"""Проверки строгого batch-сбора будущих odds от canonical calendar."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.data.providers.odds.client import OddsApiQuotaSnapshot, QuotaBudgetError
from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.orchestration.future_odds import (
    FutureOddsObservation,
    parse_nhl_future_odds,
    run_nhl_future_odds_batch,
)
from sports_forecast.service.db.models import (
    Base,
    CanonicalEvent,
    DataCycleRun,
    OddsAcquisitionAttempt,
    OddsObservation,
)
from sports_forecast.service.db.repository import CalendarRepository


NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
KICKOFF = datetime(2026, 9, 30, 23, tzinfo=UTC)


def _event(event_id: int = 1, scheduled_at: datetime = KICKOFF) -> SimpleNamespace:
    return SimpleNamespace(
        id=event_id,
        source_event_id=str(9000 + event_id),
        status="scheduled",
        scheduled_at=scheduled_at,
        home_participant="ANA",
        away_participant="BOS",
    )


def _provider_event(*, outcomes: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "id": "odds-123",
        "commence_time": "2026-09-30T23:00:00Z",
        "home_team": "Anaheim Ducks",
        "away_team": "Boston Bruins",
        "bookmakers": [
            {
                "key": "pinnacle",
                "last_update": "2026-09-26T11:55:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": outcomes
                        or [
                            {"name": "Anaheim Ducks", "price": 2.1},
                            {"name": "Boston Bruins", "price": 1.8},
                        ],
                    }
                ],
            }
        ],
    }


def _registry() -> TeamNameRegistry:
    return TeamNameRegistry.from_source_sections(
        {"ANA": "ANA", "BOS": "BOS"},
        {"ANAHEIMDUCKS": "ANA", "BOSTONBRUINS": "BOS"},
    )


def test_calendar_only_event_gets_exact_two_way_odds_with_provider_timestamps() -> None:
    observations, counts = parse_nhl_future_odds(
        [_event()], [_provider_event()], _registry(), retrieved_at=NOW
    )

    assert len(observations) == 1
    quote = observations[0]
    assert quote.canonical_event_id == 1
    assert quote.provider_event_id == "odds-123"
    assert quote.observed_at == datetime(2026, 9, 26, 11, 55, tzinfo=UTC)
    assert quote.observed_at_source == "bookmaker.last_update"
    assert quote.retrieved_at == NOW
    assert quote.values == {"home": 2.1, "away": 1.8}
    assert counts == {"provider_events": 1, "matched": 1, "missing": 0, "rejected": 0}


def test_draw_or_other_outcomes_do_not_confirm_winner_with_ot() -> None:
    three_way = _provider_event(
        outcomes=[
            {"name": "Anaheim Ducks", "price": 2.1},
            {"name": "Boston Bruins", "price": 1.8},
            {"name": "Draw", "price": 4.0},
        ]
    )

    observations, counts = parse_nhl_future_odds(
        [_event()], [three_way], _registry(), retrieved_at=NOW
    )

    assert observations == []
    assert counts["rejected"] == 1


def test_ambiguous_event_identity_and_missing_provider_time_are_rejected() -> None:
    observations, counts = parse_nhl_future_odds(
        [_event(), _event(event_id=2)], [_provider_event()], _registry(), retrieved_at=NOW
    )
    assert observations == []
    assert counts["rejected"] == 1

    without_time = _provider_event()
    bookmaker = without_time["bookmakers"][0]  # type: ignore[index]
    bookmaker.pop("last_update")
    observations, counts = parse_nhl_future_odds(
        [_event()], [without_time], _registry(), retrieved_at=NOW
    )
    assert observations == []
    assert counts["rejected"] == 1


def test_market_timestamp_takes_precedence_and_keeps_its_source_field() -> None:
    provider_event = _provider_event()
    bookmaker = provider_event["bookmakers"][0]  # type: ignore[index]
    bookmaker["markets"][0]["last_update"] = "2026-09-26T11:50:00Z"

    observations, _ = parse_nhl_future_odds(
        [_event()], [provider_event], _registry(), retrieved_at=NOW
    )

    assert observations[0].observed_at == datetime(2026, 9, 26, 11, 50, tzinfo=UTC)
    assert observations[0].observed_at_source == "market.last_update"


def test_provider_timestamp_far_after_retrieval_is_rejected() -> None:
    provider_event = _provider_event()
    bookmaker = provider_event["bookmakers"][0]  # type: ignore[index]
    bookmaker["markets"][0]["last_update"] = "2026-10-30T11:55:00Z"

    observations, counts = parse_nhl_future_odds(
        [_event()], [provider_event], _registry(), retrieved_at=NOW
    )

    assert observations == []
    assert counts["rejected"] == 1


def test_exact_kickoff_prevents_reusing_quote_after_reschedule() -> None:
    moved = _event(scheduled_at=datetime(2026, 10, 1, 1, tzinfo=UTC))

    observations, counts = parse_nhl_future_odds(
        [moved], [_provider_event()], _registry(), retrieved_at=NOW
    )

    assert observations == []
    assert counts["missing"] == 1


def test_duplicate_provider_event_or_pinnacle_h2h_is_rejected_as_ambiguous() -> None:
    duplicate_event = _provider_event()
    duplicate_event["id"] = "odds-duplicate"
    observations, counts = parse_nhl_future_odds(
        [_event()], [_provider_event(), duplicate_event], _registry(), retrieved_at=NOW
    )
    assert observations == []
    assert counts["rejected"] == 2

    duplicate_market = _provider_event()
    bookmaker = duplicate_market["bookmakers"][0]  # type: ignore[index]
    bookmaker["markets"].append(bookmaker["markets"][0])
    observations, counts = parse_nhl_future_odds(
        [_event()], [duplicate_market], _registry(), retrieved_at=NOW
    )
    assert observations == []
    assert counts["rejected"] == 1

    duplicate_bookmaker = _provider_event()
    bookmakers = duplicate_bookmaker["bookmakers"]
    assert isinstance(bookmakers, list)
    bookmakers.append(bookmakers[0])
    observations, counts = parse_nhl_future_odds(
        [_event()], [duplicate_bookmaker], _registry(), retrieved_at=NOW
    )
    assert observations == []
    assert counts["rejected"] == 1


class _FakeProvider:
    def __init__(self, payload: dict[str, Any] | list[Any] | Exception) -> None:
        self.payload = payload
        self.calls: list[tuple[datetime, datetime, bool]] = []

    def fetch_future_nhl_odds(
        self, *, commence_time_from: datetime, commence_time_to: datetime, use_cache: bool = False
    ) -> dict[str, Any] | list[Any]:
        self.calls.append((commence_time_from, commence_time_to, use_cache))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def last_quota(self) -> OddsApiQuotaSnapshot:
        return OddsApiQuotaSnapshot(requests_remaining=23, requests_used=7)


@pytest.fixture
def odds_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="9001",
                scheduled_at=KICKOFF.replace(tzinfo=None),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="ANA",
                away_participant="BOS",
            )
        )
        session.add(
            DataCycleRun(
                run_id="run-1",
                tournament="nhl",
                reason="scheduled",
                status="running",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_batch_persists_calendar_only_observation_and_attempt_idempotently(
    odds_session: Session,
) -> None:
    provider = _FakeProvider([_provider_event()])
    attempt = run_nhl_future_odds_batch(
        odds_session,
        run_id="run-1",
        now=NOW,
        provider=provider,
        team_registry=_registry(),
        clock=lambda: NOW,
    )

    observation = odds_session.scalar(select(OddsObservation))
    assert attempt.status == "success"
    assert attempt.matched_events == 1
    assert observation is not None
    assert observation.provider_event_id == "odds-123"
    assert observation.retrieved_at == NOW.replace(tzinfo=None)
    assert observation.observed_at == datetime(2026, 9, 26, 11, 55)
    assert provider.calls == [(KICKOFF, KICKOFF + timedelta(seconds=1), False)]

    run_nhl_future_odds_batch(
        odds_session,
        run_id="run-1",
        now=NOW,
        provider=provider,
        team_registry=_registry(),
        clock=lambda: NOW,
    )
    assert odds_session.scalar(select(func.count()).select_from(OddsObservation)) == 1
    assert odds_session.scalar(select(func.count()).select_from(OddsAcquisitionAttempt)) == 1
    assert len(provider.calls) == 1


def test_new_rescheduled_identity_replaces_old_later_provider_timestamp(
    odds_session: Session,
) -> None:
    repository = CalendarRepository(odds_session)
    old = FutureOddsObservation(
        canonical_event_id=1,
        market="winner",
        market_spec="winner_withOT",
        bookmaker="pinnacle",
        event_scheduled_at=KICKOFF,
        event_home_participant="ANA",
        event_away_participant="BOS",
        observed_at=datetime(2026, 9, 26, 12, 30, tzinfo=UTC),
        observed_at_source="market.last_update",
        retrieved_at=datetime(2026, 9, 26, 12, 31, tzinfo=UTC),
        provider_event_id="old-provider-event",
        values={"home": 2.1, "away": 1.8},
    )
    new = FutureOddsObservation(
        canonical_event_id=1,
        market="winner",
        market_spec="winner_withOT",
        bookmaker="pinnacle",
        event_scheduled_at=datetime(2026, 10, 1, 23, tzinfo=UTC),
        event_home_participant="ANA",
        event_away_participant="BOS",
        observed_at=datetime(2026, 9, 26, 11, 30, tzinfo=UTC),
        observed_at_source="market.last_update",
        retrieved_at=datetime(2026, 9, 26, 12, 40, tzinfo=UTC),
        provider_event_id="new-provider-event",
        values={"home": 2.3, "away": 1.7},
    )

    assert repository.upsert_odds_observation(old) is True
    canonical_event = odds_session.scalar(select(CanonicalEvent))
    assert canonical_event is not None
    canonical_event.scheduled_at = datetime(2026, 10, 1, 23)
    odds_session.flush()
    assert repository.upsert_odds_observation(new) is True
    stored = odds_session.scalar(select(OddsObservation))
    assert stored is not None
    assert stored.event_scheduled_at == datetime(2026, 10, 1, 23)
    assert stored.provider_event_id == "new-provider-event"


def test_quota_failure_is_persisted_without_a_false_observation(odds_session: Session) -> None:
    provider = _FakeProvider(QuotaBudgetError("limit"))

    attempt = run_nhl_future_odds_batch(
        odds_session,
        run_id="run-1",
        now=NOW,
        provider=provider,
        team_registry=_registry(),
        clock=lambda: NOW,
    )

    persisted = odds_session.scalar(select(OddsAcquisitionAttempt))
    assert attempt.status == "failed"
    assert attempt.failure_code == "quota_exhausted"
    assert persisted is not None
    assert persisted.requests_remaining == 23
    assert odds_session.scalar(select(func.count()).select_from(OddsObservation)) == 0


def test_provider_error_is_persisted_and_missing_market_is_not_a_failure(
    odds_session: Session,
) -> None:
    failed = run_nhl_future_odds_batch(
        odds_session,
        run_id="run-1",
        now=NOW,
        provider=_FakeProvider(requests.ConnectionError("offline")),
        team_registry=_registry(),
        clock=lambda: NOW,
    )
    assert failed.status == "failed"
    assert failed.failure_code == "provider_unavailable"

    empty_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(empty_engine)
    try:
        with Session(empty_engine) as session:
            session.add(
                CanonicalEvent(
                    sport="ice_hockey",
                    tournament="nhl",
                    source="nhl_web_api",
                    source_event_id="9002",
                    scheduled_at=KICKOFF.replace(tzinfo=None),
                    status="scheduled",
                    current_revision_sha256="b" * 64,
                    home_participant="ANA",
                    away_participant="BOS",
                )
            )
            session.add(
                DataCycleRun(
                    run_id="run-empty",
                    tournament="nhl",
                    reason="scheduled",
                    status="running",
                )
            )
            session.commit()
            empty = run_nhl_future_odds_batch(
                session,
                run_id="run-empty",
                now=NOW,
                provider=_FakeProvider([]),
                team_registry=_registry(),
                clock=lambda: NOW,
            )
            assert empty.status == "success"
            assert empty.missing_events == 1
            assert empty.failure_code is None
            assert session.scalar(select(func.count()).select_from(OddsObservation)) == 0
    finally:
        empty_engine.dispose()
