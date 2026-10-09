"""Контракты привязки source odds к canonical events."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.identity.registry import Resolution
from sports_forecast.service import odds_projection
from sports_forecast.service.app import app
from sports_forecast.service.db.models import (
    Base,
    CanonicalEvent,
    OddsAcquisitionAttempt,
    OddsObservation,
    Prediction,
    RegistryCandidateOutbox,
)
from sports_forecast.service.db.repository import CalendarRepository
from sports_forecast.service.event_readiness import evaluate_event_readiness
from sports_forecast.service.odds_projection import (
    OddsMarketColumns,
    project_odds_rows,
    sync_odds_store_observations,
)
from sports_forecast.service.routers import calendar


WINNER_COLUMNS = OddsMarketColumns(
    market="winner",
    market_spec="winner_withOT",
    bookmaker="pinnacle",
    value_columns=("pinnacle_winner_withOT_home_close", "pinnacle_winner_withOT_away_close"),
    provider_timestamp_column="pinnacle_winner_withOT_provider_observed_at",
)


def _event(event_id: int, scheduled_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=event_id,
        tournament="nhl",
        scheduled_at=scheduled_at,
        home_participant="NYR",
        away_participant="PIT",
    )


def _row(fetched_at: str, commence_time: str = "2026-10-01T23:00:00Z") -> dict[str, object]:
    return {
        "home_team_norm": "NEWYORKRANGERS",
        "away_team_norm": "PITTSBURGH PENGUINS",
        "commence_time_utc": commence_time,
        "fetched_at": fetched_at,
        "pinnacle_winner_withOT_provider_observed_at": fetched_at,
        "pinnacle_winner_withOT_home_close": 1.95,
        "pinnacle_winner_withOT_away_close": 1.88,
    }


def test_odds_link_requires_unique_exact_event_identity_and_preserves_fetched_at() -> None:
    """Одинаковые пары/дни не создают ложную связь, время линии берётся из store."""
    scheduled = datetime(2026, 10, 1, 23, tzinfo=UTC)
    events = [_event(1, scheduled)]
    odds = pd.DataFrame([_row("2026-10-01T20:00:00Z")])
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )

    linked = project_odds_rows(events, odds, [WINNER_COLUMNS], registry)

    assert len(linked) == 1
    assert linked[0].canonical_event_id == 1
    assert linked[0].event_scheduled_at == scheduled
    assert linked[0].event_home_participant == "NYR"
    assert linked[0].event_away_participant == "PIT"
    assert linked[0].observed_at == datetime(2026, 10, 1, 20, tzinfo=UTC)
    assert linked[0].values == {
        "pinnacle_winner_withOT_home_close": 1.95,
        "pinnacle_winner_withOT_away_close": 1.88,
    }


def test_strict_odds_link_waits_for_confirmed_bookmaker_aliases() -> None:
    """Неизвестное букмекерское имя не даёт line даже при legacy совпадении."""
    scheduled = datetime(2026, 10, 1, 23, tzinfo=UTC)
    events = [_event(1, scheduled)]
    odds = pd.DataFrame([_row("2026-10-01T20:00:00Z")])
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )

    strict = project_odds_rows(
        events,
        odds,
        [WINNER_COLUMNS],
        registry,
        registry_project_events={1: ("event-uuid", "league-uuid", "home-uuid", "away-uuid")},
        confirmed_bookmaker_teams={
            ("league-uuid", "NEWYORKRANGERS", scheduled): "home-uuid",
        },
    )
    assert strict == []

    confirmed = project_odds_rows(
        events,
        odds,
        [WINNER_COLUMNS],
        registry,
        registry_project_events={1: ("event-uuid", "league-uuid", "home-uuid", "away-uuid")},
        confirmed_bookmaker_teams={
            ("league-uuid", "NEWYORKRANGERS", scheduled): "home-uuid",
            ("league-uuid", "PITTSBURGH PENGUINS", scheduled): "away-uuid",
        },
    )
    assert len(confirmed) == 1
    assert confirmed[0].canonical_event_id == 1


def test_strict_odds_link_uses_same_contract_for_football() -> None:
    """Второй турнир использует ту же project identity без имён в коде."""
    scheduled = datetime(2026, 10, 1, 23, tzinfo=UTC)
    event = SimpleNamespace(
        id=11,
        tournament="epl",
        scheduled_at=scheduled,
        home_participant="ARS",
        away_participant="CHE",
    )
    row = {
        **_row("2026-10-01T20:00:00Z"),
        "home_team_norm": "Arsenal",
        "away_team_norm": "Chelsea",
    }
    linked = project_odds_rows(
        [event],
        pd.DataFrame([row]),
        [WINNER_COLUMNS],
        TeamNameRegistry(),
        registry_project_events={11: ("match-uuid", "league-uuid", "ars-uuid", "che-uuid")},
        confirmed_bookmaker_teams={
            ("league-uuid", "Arsenal", scheduled): "ars-uuid",
            ("league-uuid", "Chelsea", scheduled): "che-uuid",
        },
    )
    assert [item.canonical_event_id for item in linked] == [11]


def test_odds_sync_pins_registry_and_does_not_use_legacy_aliases(monkeypatch) -> None:
    """Strict sync обращается к закреплённому snapshot и пропускает unknown alias."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    scheduled = datetime(2026, 10, 1, 23, tzinfo=UTC)
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )
    project = SimpleNamespace(
        id="event-uuid",
        sport="ice_hockey",
        tournament_id="league-uuid",
        home_team_id="home-uuid",
        away_team_id="away-uuid",
    )
    confirmed = {"NEWYORKRANGERS": "home-uuid"}
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", "11111111-1111-4111-8111-111111111111")

    class FakeReader:
        snapshot_id = "ir1:" + "a" * 64
        event_snapshot = SimpleNamespace(event_snapshot=SimpleNamespace(events=(project,)))

        def get_event_mapping(self, event_id, session):
            return SimpleNamespace(status="resolved", project_event_id="event-uuid")

        def resolve_designation(self, *, raw_value, **kwargs):
            value = confirmed.get(raw_value)
            return Resolution("resolved" if value else "unresolved", value, "fixture")

    monkeypatch.setattr(odds_projection, "registry_event_reader_enabled", lambda: True)
    monkeypatch.setattr(odds_projection, "pin_installed_registry", lambda _session: FakeReader())
    policy = {"odds_markets": [dict(vars(WINNER_COLUMNS))]}
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_api",
                source_event_id="1",
                scheduled_at=scheduled,
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="NYR",
                away_participant="PIT",
            )
        )
        session.flush()
        frame = pd.DataFrame([_row("2026-10-01T20:00:00Z")])
        assert sync_odds_store_observations(session, "nhl", frame, policy, registry) == 0
        candidates = session.scalars(select(RegistryCandidateOutbox)).all()
        assert len(candidates) == 1
        assert '"raw_value":"PITTSBURGH PENGUINS"' in candidates[0].payload_json
        confirmed["PITTSBURGH PENGUINS"] = "away-uuid"
        assert sync_odds_store_observations(session, "nhl", frame, policy, registry) == 1
    engine.dispose()


def test_calendar_readiness_filters_legacy_odds_in_strict_mode() -> None:
    """Сохранённая до registry линия остаётся в БД, но не считается текущей."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    scheduled = datetime(2026, 10, 1, 23)
    with Session(engine) as session:
        event = CanonicalEvent(
            sport="ice_hockey",
            tournament="nhl",
            source="nhl_api",
            source_event_id="1",
            scheduled_at=scheduled,
            status="scheduled",
            current_revision_sha256="a" * 64,
            home_participant="NYR",
            away_participant="PIT",
        )
        session.add(event)
        session.flush()
        session.add(
            OddsObservation(
                canonical_event_id=event.id,
                market="winner",
                market_spec="winner_withOT",
                bookmaker="pinnacle",
                event_scheduled_at=scheduled,
                event_home_participant="NYR",
                event_away_participant="PIT",
                observed_at=datetime(2026, 10, 1, 20),
                values_json='{"home":1.95,"away":1.88}',
                source="the_odds_api",
            )
        )
        session.flush()
        repository = CalendarRepository(session)
        _, legacy, _ = repository.get_readiness_data([event])
        _, strict, _ = repository.get_readiness_data(
            [event], registry_snapshot_id="ir1:" + "a" * 64
        )
        assert len(legacy[event.id]) == 1
        assert strict[event.id] == []
    engine.dispose()


def test_odds_link_rejects_legacy_row_without_market_provider_timestamp() -> None:
    """Store retrieval timestamp alone cannot prove market freshness or semantics."""
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )
    legacy_row = _row("2026-10-01T22:00:00Z")
    legacy_row.pop("pinnacle_winner_withOT_provider_observed_at")
    assert (
        project_odds_rows(
            [_event(1, datetime(2026, 10, 1, 23, tzinfo=UTC))],
            pd.DataFrame([legacy_row]),
            [WINNER_COLUMNS],
            registry,
        )
        == []
    )


def test_odds_link_uses_market_provider_timestamp_not_store_fetch_timestamp() -> None:
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )
    row = {
        **_row("2026-10-01T22:00:00Z"),
        "pinnacle_winner_withOT_provider_observed_at": "2026-10-01T20:00:00Z",
    }
    linked = project_odds_rows(
        [_event(1, datetime(2026, 10, 1, 23, tzinfo=UTC))],
        pd.DataFrame([row]),
        [WINNER_COLUMNS],
        registry,
    )
    assert len(linked) == 1
    assert linked[0].observed_at == datetime(2026, 10, 1, 20, tzinfo=UTC)


def test_odds_link_leaves_same_team_day_ambiguity_unlinked() -> None:
    """Две canonical встречи с одной парой и kickoff не допускают произвольный выбор."""
    scheduled = datetime(2026, 10, 1, 23, tzinfo=UTC)
    events = [_event(1, scheduled), _event(2, scheduled)]
    registry = TeamNameRegistry.from_source_sections({}, {})

    linked = project_odds_rows(
        events,
        pd.DataFrame([_row("2026-10-01T20:00:00Z")]),
        [WINNER_COLUMNS],
        registry,
    )

    assert linked == []


def test_odds_for_old_kickoff_does_not_link_after_calendar_reschedule() -> None:
    """Новый импорт после переноса не связывает старую линию с новым kickoff."""
    moved_event = _event(7, datetime(2026, 10, 2, 1, tzinfo=UTC))
    registry = TeamNameRegistry.from_source_sections({}, {})

    linked = project_odds_rows(
        [moved_event],
        pd.DataFrame([_row("2026-10-01T20:00:00Z")]),
        [WINNER_COLUMNS],
        registry,
    )

    assert linked == []


def test_calendar_readiness_supports_football_market_policy(monkeypatch) -> None:
    """Футбольный market проходит общий event API и собственную bookmaker policy."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        event = CanonicalEvent(
            sport="football",
            tournament="epl",
            source="fixture_feed",
            source_event_id="fixture-1",
            scheduled_at=datetime(2026, 9, 26, 1),
            status="scheduled",
            current_revision_sha256="a" * 64,
            home_participant="ARS",
            away_participant="CHE",
        )
        session.add(event)
        session.flush()
        session.add(
            Prediction(
                match_id="fixture-1",
                tournament="epl",
                market="winner",
                market_spec="winner",
                model_version="fixture-model",
                algorithm="fixture",
                featureset="fixture",
                predictions_json='{"home_win":0.5,"draw":0.25,"away_win":0.25}',
                prediction_ts=datetime(2026, 9, 26, 0),
                status="ok",
            )
        )
        session.add(
            OddsObservation(
                canonical_event_id=event.id,
                market="winner",
                market_spec="winner",
                bookmaker="examplebook",
                event_scheduled_at=datetime(2026, 9, 26, 1),
                event_home_participant="ARS",
                event_away_participant="CHE",
                observed_at=datetime(2026, 9, 25, 23),
                values_json='{"home":2.0,"draw":3.2,"away":4.0}',
                source="fixture_feed",
            )
        )
        session.commit()

    @contextmanager
    def _get_test_session():
        test_session = Session(engine)
        try:
            yield test_session
        finally:
            test_session.close()

    monkeypatch.setattr(calendar, "get_session", _get_test_session)
    monkeypatch.setattr(calendar, "utc_now", lambda: datetime(2026, 9, 26, 0, tzinfo=UTC))
    try:
        response = TestClient(app).get("/calendar/epl", params={"period": "today"})
    finally:
        engine.dispose()

    assert response.status_code == 200
    item = response.json()["events"][0]
    assert item["prediction_readiness"]["status"] == "ready"
    assert item["prediction_readiness"]["required"] == ["winner:winner"]
    assert item["odds_readiness"]["status"] == "ready"
    assert item["odds_readiness"]["required"] == ["winner:winner:examplebook"]
    assert item["readiness"]["status"] == "ready"


def test_odds_store_sync_is_idempotent_and_keeps_link_after_event_move() -> None:
    """Повторная синхронизация не обновляет fetched_at, перенос не удаляет известную линию."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    registry = TeamNameRegistry.from_source_sections(
        {"NYR": "NYR", "PIT": "PIT"},
        {"NEWYORKRANGERS": "NYR", "PITTSBURGHPENGUINS": "PIT"},
    )
    policy = {
        "odds_markets": [
            {
                "market": "winner",
                "market_spec": "winner_withOT",
                "bookmaker": "pinnacle",
                "value_columns": list(WINNER_COLUMNS.value_columns),
                "provider_timestamp_column": WINNER_COLUMNS.provider_timestamp_column,
            }
        ]
    }
    frame = pd.DataFrame([_row("2026-10-01T20:00:00Z")])
    with Session(engine) as session:
        event = CanonicalEvent(
            sport="ice_hockey",
            tournament="nhl",
            source="nhl_web_api",
            source_event_id="event-1",
            scheduled_at=datetime(2026, 10, 1, 23),
            status="scheduled",
            current_revision_sha256="a" * 64,
            home_participant="NYR",
            away_participant="PIT",
        )
        session.add(event)
        session.commit()
        assert sync_odds_store_observations(session, "nhl", frame, policy, registry) == 1
        assert sync_odds_store_observations(session, "nhl", frame, policy, registry) == 0
        observation = session.query(OddsObservation).one()
        observed_at = observation.observed_at
        event.scheduled_at = datetime(2026, 10, 2, 1)
        session.commit()
        assert sync_odds_store_observations(session, "nhl", frame, policy, registry) == 0
        observation = session.query(OddsObservation).one()
        assert observation.observed_at == observed_at
        readiness = evaluate_event_readiness(
            cast(CanonicalEvent, event),
            [],
            [observation],
            {
                "preparation_deadline_hours": 6,
                "prediction_freshness_hours": 24,
                "odds_freshness_hours": 6,
                "prediction_markets": [{"market": "winner", "market_spec": "winner_withOT"}],
                "odds_markets": [
                    {
                        "market": "winner",
                        "market_spec": "winner_withOT",
                        "bookmaker": "pinnacle",
                    }
                ],
            },
            datetime(2026, 10, 2, 0, tzinfo=UTC),
        )
        assert readiness["odds_readiness"]["status"] == "stale"
        assert readiness["odds_readiness"]["reason_code"] == "required_market_missing_or_stale"
    engine.dispose()


def test_missing_partial_stale_failed_and_deadline_readiness_states() -> None:
    """Состояния следуют отдельным required markets, timestamps и preparation deadline."""
    now = datetime(2026, 9, 26, 0, tzinfo=UTC)
    event = SimpleNamespace(
        id=3,
        tournament="epl",
        status="scheduled",
        scheduled_at=datetime(2026, 9, 26, 10, tzinfo=UTC),
    )
    policy = {
        "preparation_deadline_hours": 4,
        "prediction_freshness_hours": 3,
        "odds_freshness_hours": 1,
        "prediction_markets": [
            {"market": "winner", "market_spec": "winner"},
            {"market": "total", "market_spec": "total_over"},
        ],
        "odds_markets": [{"market": "winner", "market_spec": "winner", "bookmaker": "examplebook"}],
    }
    missing = evaluate_event_readiness(cast(CanonicalEvent, event), [], [], policy, now)
    assert missing["prediction_readiness"]["status"] == "pending"
    assert missing["odds_readiness"]["status"] == "missing"
    assert missing["readiness"]["status"] == "waiting"

    prediction = SimpleNamespace(
        market="winner",
        market_spec="winner",
        prediction_ts=now,
        status="ok",
        match_datetime=None,
        home_player=None,
        away_player=None,
    )
    odds = SimpleNamespace(
        market="winner",
        market_spec="winner",
        bookmaker="examplebook",
        observed_at=datetime(2026, 9, 25, 20, tzinfo=UTC),
    )
    partial = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [cast(Prediction, prediction)],
        [cast(OddsObservation, odds)],
        policy,
        now,
    )
    assert partial["prediction_readiness"]["status"] == "partial"
    assert partial["odds_readiness"]["status"] == "stale"
    assert partial["readiness"]["status"] == "partial"

    failed_prediction = SimpleNamespace(
        market="total",
        market_spec="total_over",
        prediction_ts=now,
        status="error",
        match_datetime=None,
        home_player=None,
        away_player=None,
    )
    after_deadline = datetime(2026, 9, 26, 7, tzinfo=UTC)
    failed = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [cast(Prediction, failed_prediction)],
        [],
        policy,
        after_deadline,
    )
    assert failed["prediction_readiness"]["status"] == "failed"
    assert failed["odds_readiness"]["status"] == "missing"
    assert failed["readiness"]["status"] == "error"


def test_canonical_event_move_marks_existing_prediction_for_review() -> None:
    """Изменённый kickoff не считается готовым на основании старого Prediction."""
    event = SimpleNamespace(
        id=8,
        tournament="epl",
        status="scheduled",
        scheduled_at=datetime(2026, 9, 26, 10, tzinfo=UTC),
        home_participant="ARS",
        away_participant="CHE",
    )
    prediction = SimpleNamespace(
        market="winner",
        market_spec="winner",
        prediction_ts=datetime(2026, 9, 25, 12, tzinfo=UTC),
        match_datetime=datetime(2026, 9, 26, 9, tzinfo=UTC),
        home_player="ARS",
        away_player="CHE",
        status="ok",
    )
    policy = {
        "preparation_deadline_hours": 4,
        "prediction_freshness_hours": 48,
        "odds_freshness_hours": 24,
        "prediction_markets": [{"market": "winner", "market_spec": "winner"}],
        "odds_markets": [{"market": "winner", "market_spec": "winner", "bookmaker": "x"}],
    }

    readiness = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [cast(Prediction, prediction)],
        [],
        policy,
        datetime(2026, 9, 26, 0, tzinfo=UTC),
    )

    assert readiness["calendar_readiness"] == "changed"
    assert readiness["prediction_readiness"]["status"] == "partial"
    assert readiness["prediction_readiness"]["reason_code"] == "event_identity_changed"
    assert readiness["readiness"]["reason_code"] == "event_identity_changed"


def test_odds_failure_is_event_scoped_deadline_aware_and_superseded_by_success() -> None:
    event = SimpleNamespace(
        id=44,
        tournament="nhl",
        status="scheduled",
        scheduled_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        home_participant="NYR",
        away_participant="PIT",
    )
    policy = {
        "preparation_deadline_hours": 6,
        "prediction_freshness_hours": 24,
        "odds_freshness_hours": 6,
        "prediction_markets": [{"market": "winner", "market_spec": "winner_withOT"}],
        "odds_markets": [
            {"market": "winner", "market_spec": "winner_withOT", "bookmaker": "pinnacle"}
        ],
    }
    attempt = SimpleNamespace(
        tournament="nhl",
        window_from=datetime(2026, 10, 1, 12),
        window_to=datetime(2026, 10, 1, 12),
        retrieved_at=datetime(2026, 10, 1, 6, 30),
        status="failed",
        failure_code="quota_exhausted",
    )
    attempt_row = cast(OddsAcquisitionAttempt, attempt)
    now = datetime(2026, 10, 1, 7, tzinfo=UTC)

    failed = evaluate_event_readiness(
        cast(CanonicalEvent, event), [], [], policy, now, odds_attempts=[attempt_row]
    )
    assert failed["odds_readiness"]["status"] == "failed"
    assert failed["odds_readiness"]["reason_code"] == "quota_exhausted"
    assert failed["odds_readiness"]["last_success_at"] is None
    assert failed["odds_readiness"]["last_attempt_at"] == now.replace(hour=6, minute=30)

    early = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [],
        [],
        policy,
        datetime(2026, 10, 1, 5, tzinfo=UTC),
        odds_attempts=[attempt_row],
    )
    assert early["odds_readiness"]["status"] == "missing"

    far_failure = SimpleNamespace(
        **{**attempt.__dict__, "retrieved_at": datetime(2026, 10, 1, 5, 30)}
    )
    far_failure_row = cast(OddsAcquisitionAttempt, far_failure)
    still_missing = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [],
        [],
        policy,
        now,
        odds_attempts=[far_failure_row],
    )
    assert still_missing["odds_readiness"]["status"] == "missing"

    successful_attempt = SimpleNamespace(
        **{**attempt.__dict__, "retrieved_at": datetime(2026, 10, 1, 7), "status": "success"}
    )
    successful_attempt_row = cast(OddsAcquisitionAttempt, successful_attempt)
    recovered = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [],
        [],
        policy,
        datetime(2026, 10, 1, 8, tzinfo=UTC),
        odds_attempts=[attempt_row, successful_attempt_row],
    )
    assert recovered["odds_readiness"]["status"] == "missing"
    assert recovered["odds_readiness"]["last_attempt_at"] == datetime(2026, 10, 1, 7, tzinfo=UTC)

    older_observation = SimpleNamespace(
        market="winner",
        market_spec="winner_withOT",
        bookmaker="pinnacle",
        event_scheduled_at=event.scheduled_at,
        event_home_participant="NYR",
        event_away_participant="PIT",
        observed_at=datetime(2026, 10, 1, 6, 15, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 1, 6, 20, tzinfo=UTC),
        status="success",
    )
    failure_after_success = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [],
        [cast(OddsObservation, older_observation)],
        policy,
        now,
        odds_attempts=[attempt_row],
    )
    assert failure_after_success["odds_readiness"]["status"] == "failed"
    assert failure_after_success["odds_readiness"]["last_success_at"] == datetime(
        2026, 10, 1, 6, 15, tzinfo=UTC
    )


def test_fresh_failed_prediction_cannot_be_reported_ready() -> None:
    """Свежий timestamp failed prediction не перекрывает факт failed результата."""
    event = SimpleNamespace(
        id=9,
        tournament="epl",
        status="scheduled",
        scheduled_at=datetime(2026, 9, 26, 10, tzinfo=UTC),
        home_participant="ARS",
        away_participant="CHE",
    )
    failed_prediction = SimpleNamespace(
        market="winner",
        market_spec="winner",
        prediction_ts=datetime(2026, 9, 26, 0, tzinfo=UTC),
        match_datetime=datetime(2026, 9, 26, 10, tzinfo=UTC),
        home_player="ARS",
        away_player="CHE",
        status="error",
    )
    readiness = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [cast(Prediction, failed_prediction)],
        [],
        {
            "preparation_deadline_hours": 4,
            "prediction_freshness_hours": 24,
            "odds_freshness_hours": 24,
            "prediction_markets": [{"market": "winner", "market_spec": "winner"}],
            "odds_markets": [
                {"market": "winner", "market_spec": "winner", "bookmaker": "examplebook"}
            ],
        },
        datetime(2026, 9, 26, 0, tzinfo=UTC),
    )

    assert readiness["prediction_readiness"]["status"] == "failed"
    assert readiness["readiness"]["status"] == "error"


def test_future_provider_timestamp_cannot_make_odds_ready() -> None:
    event = SimpleNamespace(
        id=12,
        tournament="nhl",
        status="scheduled",
        scheduled_at=datetime(2026, 10, 31, 23, tzinfo=UTC),
        home_participant="NYR",
        away_participant="PIT",
    )
    future_odds = SimpleNamespace(
        market="winner",
        market_spec="winner_withOT",
        bookmaker="pinnacle",
        observed_at=datetime(2026, 10, 30, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 9, 26, 12, tzinfo=UTC),
        event_scheduled_at=event.scheduled_at,
        event_home_participant="NYR",
        event_away_participant="PIT",
    )

    readiness = evaluate_event_readiness(
        cast(CanonicalEvent, event),
        [],
        [cast(OddsObservation, future_odds)],
        {
            "preparation_deadline_hours": 6,
            "prediction_freshness_hours": 24,
            "odds_freshness_hours": 6,
            "prediction_markets": [],
            "odds_markets": [
                {"market": "winner", "market_spec": "winner_withOT", "bookmaker": "pinnacle"}
            ],
        },
        datetime(2026, 9, 26, 12, tzinfo=UTC),
    )

    assert readiness["odds_readiness"]["status"] == "stale"
    assert readiness["odds_readiness"]["available"] == []
