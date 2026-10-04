"""Контрактные тесты идентичности project events и версионного bridge."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.events import (
    CanonicalEventRef,
    EventIdentitySnapshot,
    EventRegistryMapping,
    RegistryEventResolver,
    backfill_event_bridge,
    get_event_mapping,
    load_event_snapshot,
    put_event_mapping,
)
from sports_forecast.service.db.models import Base, CanonicalEvent, RegistryIdentitySnapshot


def make_registry(tmp_path: Path) -> EntityRegistry:
    registry = EntityRegistry(tmp_path / "identity.sqlite3")
    registry.initialize()
    return registry


def make_fixture(tmp_path: Path):
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="soccer")
    home = registry.create_entity("team", "North", sport="soccer")
    away = registry.create_entity("team", "South", sport="soccer")
    event = registry.create_entity("event", "North v South", sport="soccer")
    scope = {"sport": "soccer", "tournament": tournament.id}
    registry.add_designation(
        entity_id=tournament.id,
        source="fixture-feed",
        kind="tournament",
        scope={"sport": "soccer"},
        value_kind="name",
        raw_value="League",
        state="confirmed",
    )
    registry.add_designation(
        entity_id=home.id,
        source="fixture-feed",
        kind="team",
        scope=scope,
        value_kind="name",
        raw_value="North",
        state="confirmed",
    )
    registry.add_designation(
        entity_id=away.id,
        source="fixture-feed",
        kind="team",
        scope=scope,
        value_kind="name",
        raw_value="South",
        state="confirmed",
    )
    registry.add_designation(
        entity_id=event.id,
        source="fixture-feed",
        kind="event",
        scope=scope,
        value_kind="external_id",
        raw_value="source-event-1",
        state="confirmed",
    )
    starts = datetime(2026, 10, 4, 17, tzinfo=UTC)
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=starts,
        actor="owner",
        reason="Подтверждённый состав события",
    )
    snapshot = EventIdentitySnapshot.from_registry(registry)
    ref = CanonicalEventRef(
        canonical_event_id=11,
        sport="soccer",
        tournament="League",
        source="fixture-feed",
        source_event_id="source-event-1",
        scheduled_at=starts,
        home_participant="North",
        away_participant="South",
    )
    return registry, snapshot, ref, snapshot.events[0], tournament, home, away


def test_same_confirmed_source_event_keeps_project_uuid_after_schedule_move(tmp_path) -> None:
    _, snapshot, ref, event, *_ = make_fixture(tmp_path)
    moved = CanonicalEventRef(
        **{
            **ref.__dict__,
            "scheduled_at": ref.scheduled_at + timedelta(hours=2),
            "canonical_event_id": 12,
        }
    )

    result = RegistryEventResolver(snapshot).resolve(moved)

    assert result.status == "resolved"
    assert result.project_event_id == event.id
    assert "source" in result.reason.lower()


def test_pending_candidate_for_confirmed_entity_does_not_override_alias(
    tmp_path: Path,
) -> None:
    registry, _, ref, event, tournament, home, _ = make_fixture(tmp_path)
    registry.add_designation(
        entity_id=home.id,
        source="fixture-feed",
        kind="team",
        scope={"sport": "soccer", "tournament": tournament.id},
        value_kind="name",
        raw_value="North",
        state="pending",
        valid_from="2026-10-01T00:00:00Z",
        valid_until="2026-11-01T00:00:00Z",
    )

    snapshot = EventIdentitySnapshot.from_registry(registry)
    result = RegistryEventResolver(snapshot).resolve(ref)

    assert result.status == "resolved"
    assert result.project_event_id == event.id
    assert (
        RegistryEventResolver(snapshot).resolve(replace(ref, scheduled_at=None)).project_event_id
        == event.id
    )


def test_multiple_exact_time_project_events_are_ambiguous(tmp_path) -> None:
    registry, _, ref, _, tournament, home, away = make_fixture(tmp_path)
    duplicate = registry.create_entity("event", "Duplicate event", sport="soccer")
    registry.set_event_relation(
        duplicate.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=ref.scheduled_at,
        actor="owner",
        reason="Синтетический повтор матча",
    )
    snapshot = EventIdentitySnapshot.from_registry(registry)
    without_source_id = CanonicalEventRef(**{**ref.__dict__, "source_event_id": "new-source-event"})

    result = RegistryEventResolver(snapshot).resolve(without_source_id)

    assert result.status == "ambiguous"
    assert result.project_event_id is None
    assert len(result.candidate_ids) == 2


def test_missing_confirmed_participant_or_time_never_auto_resolves(tmp_path) -> None:
    _, snapshot, ref, *_ = make_fixture(tmp_path)
    without_participant = CanonicalEventRef(
        **{**ref.__dict__, "source_event_id": "new-id", "home_participant": "Unknown"}
    )
    without_time = CanonicalEventRef(
        **{**ref.__dict__, "source_event_id": "new-id", "scheduled_at": None}
    )

    assert RegistryEventResolver(snapshot).resolve(without_participant).status == "unresolved"
    assert RegistryEventResolver(snapshot).resolve(without_time).status == "unresolved"


def test_confirmed_source_event_conflicts_with_different_confirmed_team(tmp_path: Path) -> None:
    registry, _, ref, _, tournament, _, _ = make_fixture(tmp_path)
    other = registry.create_entity("team", "East", sport="soccer")
    registry.add_designation(
        entity_id=other.id,
        source="fixture-feed",
        kind="team",
        scope={"sport": "soccer", "tournament": tournament.id},
        value_kind="name",
        raw_value="East",
        state="confirmed",
    )
    snapshot = EventIdentitySnapshot.from_registry(registry)
    contradictory = CanonicalEventRef(**{**ref.__dict__, "home_participant": "East"})

    result = RegistryEventResolver(snapshot).resolve(contradictory)

    assert result.status == "conflict"
    assert result.project_event_id is None


def test_rescheduling_updates_event_relation_revision_and_audit(tmp_path: Path) -> None:
    registry, _, _, event, tournament, home, away = make_fixture(tmp_path)
    moved = datetime(2026, 10, 5, 17, tzinfo=UTC)

    relation = registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=moved,
        actor="owner",
        reason="Перенос расписания",
        expected_revision=1,
    )

    assert relation.event_id == event.id
    assert relation.revision == 2
    assert relation.scheduled_at == "2026-10-05T17:00:00.000000Z"
    audit = registry.list_event_relation_audit(event.id)
    assert len(audit) == 2
    assert audit[-1].reason == "Перенос расписания"


def test_bridge_is_snapshot_pinned_and_stores_unresolved_legacy_row(tmp_path) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        legacy = CanonicalEvent(
            sport="soccer",
            tournament="unknown-league",
            source="fixture-feed",
            source_event_id="legacy-id",
            scheduled_at=datetime(2026, 10, 4, 17),
            status="scheduled",
            current_revision_sha256="a" * 64,
            home_participant=None,
            away_participant=None,
        )
        resolved = CanonicalEvent(
            sport="soccer",
            tournament="League",
            source="fixture-feed",
            source_event_id="source-event-1",
            scheduled_at=datetime(2026, 10, 4, 17),
            status="scheduled",
            current_revision_sha256="b" * 64,
            home_participant="North",
            away_participant="South",
        )
        session.add_all([legacy, resolved])
        session.flush()
        legacy_id, resolved_id = legacy.id, resolved.id
        _, snapshot_a, _, event, *_ = make_fixture(tmp_path / "identity-a")
        _, snapshot_b, _, _, *_ = make_fixture(tmp_path / "identity-b")
        unresolved = put_event_mapping(
            session,
            snapshot=snapshot_a,
            canonical_event_id=legacy_id,
            project_event_id=None,
            status="unresolved",
            reason="Участники не подтверждены",
            policy_version="strict-v1",
        )
        mapping_a = put_event_mapping(
            session,
            snapshot=snapshot_a,
            canonical_event_id=resolved_id,
            project_event_id=event.id,
            status="resolved",
            reason="Подтверждённый source event ID",
            policy_version="strict-v1",
        )
        mapping_b = put_event_mapping(
            session,
            snapshot=snapshot_b,
            canonical_event_id=resolved_id,
            project_event_id=snapshot_b.events[0].id,
            status="resolved",
            reason="Другой закреплённый снимок",
            policy_version="strict-v1",
        )

        assert unresolved.project_event_id is None
        assert (
            get_event_mapping(
                session, snapshot_id=snapshot_a.snapshot_id, canonical_event_id=legacy_id
            ).status
            == "unresolved"
        )
        assert (
            get_event_mapping(
                session, snapshot_id=snapshot_a.snapshot_id, canonical_event_id=resolved_id
            ).project_event_id
            == event.id
        )
        assert (
            get_event_mapping(
                session, snapshot_id=snapshot_b.snapshot_id, canonical_event_id=resolved_id
            ).project_event_id
            == mapping_b.project_event_id
        )
        assert mapping_a.project_event_id != mapping_b.project_event_id
        legacy_row = session.scalar(
            select(CanonicalEvent).where(CanonicalEvent.__table__.c.id == legacy_id)
        )
        assert legacy_row is not None
        assert legacy_row.home_participant is None
    engine.dispose()


def test_backfill_defaults_to_dry_run_and_plans_every_legacy_row(tmp_path) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _, snapshot, _, *_ = make_fixture(tmp_path / "identity")
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="soccer",
                tournament="Unknown",
                source="fixture-feed",
                source_event_id="legacy-without-participants",
                scheduled_at=datetime(2026, 10, 4, 17),
                status="scheduled",
                current_revision_sha256="c" * 64,
            )
        )
        session.flush()

        plan = backfill_event_bridge(session, snapshot=snapshot)

        assert plan.dry_run is True
        assert plan.counts["unresolved"] == 1
        assert session.scalars(select(EventRegistryMapping)).all() == []
    engine.dispose()


def test_batch_backfill_rejects_two_source_events_claiming_one_project_event(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _, snapshot, _, event, *_ = make_fixture(tmp_path / "identity")
    with Session(engine) as session:
        starts = datetime(2026, 10, 4, 17)
        session.add_all(
            [
                CanonicalEvent(
                    sport="soccer",
                    tournament="League",
                    source="fixture-feed",
                    source_event_id=source_id,
                    scheduled_at=starts,
                    status="scheduled",
                    current_revision_sha256=sha,
                    home_participant="North",
                    away_participant="South",
                )
                for source_id, sha in (("bookie-1", "d" * 64), ("bookie-2", "e" * 64))
            ]
        )
        session.flush()

        plan = backfill_event_bridge(session, snapshot=snapshot)

        assert plan.counts["ambiguous"] == 2
        assert all(result.project_event_id is None for result in plan.mappings)
        assert all(result.candidate_ids == (event.id,) for result in plan.mappings)
    engine.dispose()


def test_confirmed_source_key_history_stays_resolved_while_new_competitor_is_ambiguous(
    tmp_path: Path,
) -> None:
    _, snapshot, ref, event, *_ = make_fixture(tmp_path)
    resolver = RegistryEventResolver(snapshot)
    historical = CanonicalEventRef(**{**ref.__dict__, "canonical_event_id": 101})
    historical_revision = CanonicalEventRef(**{**ref.__dict__, "canonical_event_id": 102})
    new_unconfirmed_id = CanonicalEventRef(
        **{
            **ref.__dict__,
            "canonical_event_id": 103,
            "source_event_id": "new-bookmaker-id",
        }
    )

    results = resolver.resolve_many((historical, historical_revision, new_unconfirmed_id))

    assert [item.status for item in results] == ["resolved", "resolved", "ambiguous"]
    assert [item.project_event_id for item in results] == [event.id, event.id, None]


def test_rebackfill_preserves_existing_auto_mapping_and_marks_late_competitor_ambiguous(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _, snapshot, ref, event, *_ = make_fixture(tmp_path / "identity")
    with Session(engine) as session:
        original = CanonicalEvent(
            sport=ref.sport,
            tournament=ref.tournament,
            source=ref.source,
            source_event_id="bookie-1",
            scheduled_at=ref.scheduled_at,
            status="scheduled",
            current_revision_sha256="5" * 64,
            home_participant=ref.home_participant,
            away_participant=ref.away_participant,
        )
        session.add(original)
        session.flush()
        first_plan = backfill_event_bridge(session, snapshot=snapshot, apply=True)
        assert first_plan.mappings[0].status == "resolved"
        previous = get_event_mapping(
            session,
            snapshot_id=snapshot.snapshot_id,
            canonical_event_id=original.id,
        )
        previous_identity = (
            previous.project_event_id,
            previous.status,
            previous.reason,
            previous.policy_version,
            previous.decision_id,
        )

        late = CanonicalEvent(
            sport=ref.sport,
            tournament=ref.tournament,
            source=ref.source,
            source_event_id="bookie-2",
            scheduled_at=ref.scheduled_at,
            status="scheduled",
            current_revision_sha256="6" * 64,
            home_participant=ref.home_participant,
            away_participant=ref.away_participant,
        )
        session.add(late)
        session.flush()

        second_plan = backfill_event_bridge(session, snapshot=snapshot, apply=True)

        assert [item.status for item in second_plan.mappings] == ["resolved", "ambiguous"]
        saved_previous = get_event_mapping(
            session,
            snapshot_id=snapshot.snapshot_id,
            canonical_event_id=original.id,
        )
        assert (
            saved_previous.project_event_id,
            saved_previous.status,
            saved_previous.reason,
            saved_previous.policy_version,
            saved_previous.decision_id,
        ) == previous_identity
        assert saved_previous.project_event_id == event.id
        assert (
            get_event_mapping(
                session,
                snapshot_id=snapshot.snapshot_id,
                canonical_event_id=late.id,
            ).status
            == "ambiguous"
        )
    engine.dispose()


def test_resolved_mapping_requires_project_event_in_frozen_projection(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _, snapshot, _, _, *_ = make_fixture(tmp_path / "identity")
    with Session(engine) as session:
        canonical = CanonicalEvent(
            sport="soccer",
            tournament="League",
            source="fixture-feed",
            source_event_id="invalid-target-test",
            scheduled_at=datetime(2026, 10, 4, 17),
            status="scheduled",
            current_revision_sha256="7" * 64,
        )
        session.add(canonical)
        session.flush()
        with pytest.raises(ValueError, match="frozen projection|проекц"):
            put_event_mapping(
                session,
                snapshot=snapshot,
                canonical_event_id=canonical.id,
                project_event_id="00000000-0000-0000-0000-000000000001",
                status="resolved",
                reason="Forged UUID",
                policy_version=snapshot.policy_version,
            )

        assert session.get(RegistryIdentitySnapshot, snapshot.snapshot_id) is None
    engine.dispose()


def test_snapshot_rejects_unsupported_normalization_version(tmp_path: Path) -> None:
    _, snapshot, _, *_ = make_fixture(tmp_path)
    payload = json.loads(snapshot.projection_json)
    payload["normalization_version"] = "future-normalizer-v2"
    changed_projection = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(changed_projection.encode("utf-8")).hexdigest()
    unsupported = replace(
        snapshot,
        normalization_version="future-normalizer-v2",
        projection_sha256=digest,
        projection_json=changed_projection,
        snapshot_id=f"ev1:{digest}",
    )

    with pytest.raises(ValueError, match="normalization|нормализац"):
        RegistryEventResolver(unsupported)


def test_resolver_selects_temporal_alias_and_never_reuses_expired_alias(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="soccer")
    home_old = registry.create_entity("team", "Old club", sport="soccer")
    home_new = registry.create_entity("team", "New club", sport="soccer")
    away = registry.create_entity("team", "Opponent", sport="soccer")
    event_old = registry.create_entity("event", "Old fixture", sport="soccer")
    event_new = registry.create_entity("event", "New fixture", sport="soccer")
    event_future = registry.create_entity("event", "Future fixture", sport="soccer")
    tournament_scope = {"sport": "soccer"}
    team_scope = {"sport": "soccer", "tournament": tournament.id}
    registry.add_designation(
        entity_id=tournament.id,
        source="feed",
        kind="tournament",
        scope=tournament_scope,
        value_kind="name",
        raw_value="League",
        state="confirmed",
    )
    for team_id, start, end in (
        (home_old.id, "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"),
        (home_new.id, "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"),
    ):
        registry.add_designation(
            entity_id=team_id,
            source="feed",
            kind="team",
            scope=team_scope,
            value_kind="name",
            raw_value="Shared",
            state="confirmed",
            valid_from=start,
            valid_until=end,
        )
    for event_id, start, end in (
        (event_old.id, "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"),
        (event_new.id, "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"),
    ):
        registry.add_designation(
            entity_id=event_id,
            source="feed",
            kind="event",
            scope=team_scope,
            value_kind="external_id",
            raw_value="season-key",
            state="confirmed",
            valid_from=start,
            valid_until=end,
        )
    registry.add_designation(
        entity_id=away.id,
        source="feed",
        kind="team",
        scope=team_scope,
        value_kind="name",
        raw_value="Opponent",
        state="confirmed",
    )
    dates = {
        event_old.id: datetime(2020, 6, 1, 17, tzinfo=UTC),
        event_new.id: datetime(2022, 6, 1, 17, tzinfo=UTC),
        event_future.id: datetime(2024, 6, 1, 17, tzinfo=UTC),
    }
    for event_id, home_id in (
        (event_old.id, home_old.id),
        (event_new.id, home_new.id),
        (event_future.id, home_old.id),
    ):
        registry.set_event_relation(
            event_id,
            tournament_id=tournament.id,
            home_team_id=home_id,
            away_team_id=away.id,
            scheduled_at=dates[event_id],
            actor="owner",
            reason="Тест temporal alias",
        )
    resolver = RegistryEventResolver(EventIdentitySnapshot.from_registry(registry))

    def result(at: datetime | None):
        return resolver.resolve(
            CanonicalEventRef(
                canonical_event_id=1,
                sport="soccer",
                tournament="League",
                source="feed",
                source_event_id="not-designated",
                scheduled_at=at,
                home_participant="Shared",
                away_participant="Opponent",
            )
        )

    assert result(dates[event_old.id]).project_event_id == event_old.id
    assert result(dates[event_new.id]).project_event_id == event_new.id
    assert result(dates[event_future.id]).status == "unresolved"
    assert result(None).status == "ambiguous"

    def source_result(at: datetime | None):
        return resolver.resolve(
            CanonicalEventRef(
                canonical_event_id=2,
                sport="soccer",
                tournament="League",
                source="feed",
                source_event_id="season-key",
                scheduled_at=at,
                home_participant="Shared",
                away_participant="Opponent",
            )
        )

    assert source_result(dates[event_old.id]).project_event_id == event_old.id
    assert source_result(dates[event_new.id]).project_event_id == event_new.id
    assert source_result(dates[event_future.id]).status == "unresolved"
    assert source_result(None).status == "ambiguous"
    stale_source_with_unknown_teams = CanonicalEventRef(
        canonical_event_id=4,
        sport="soccer",
        tournament="League",
        source="feed",
        source_event_id="season-key",
        scheduled_at=dates[event_future.id],
        home_participant="Unknown",
        away_participant="Opponent",
    )
    assert resolver.resolve(stale_source_with_unknown_teams).status == "unresolved"


def test_tournament_alias_is_selected_by_event_time(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament_old = registry.create_entity("tournament", "Old league", sport="soccer")
    tournament_new = registry.create_entity("tournament", "New league", sport="soccer")
    home_old = registry.create_entity("team", "Old home", sport="soccer")
    away_old = registry.create_entity("team", "Old away", sport="soccer")
    home_new = registry.create_entity("team", "New home", sport="soccer")
    away_new = registry.create_entity("team", "New away", sport="soccer")
    event_old = registry.create_entity("event", "Old league fixture", sport="soccer")
    event_new = registry.create_entity("event", "New league fixture", sport="soccer")
    registry.add_designation(
        entity_id=tournament_old.id,
        source="feed",
        kind="tournament",
        scope={"sport": "soccer"},
        value_kind="name",
        raw_value="League",
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2021-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=tournament_new.id,
        source="feed",
        kind="tournament",
        scope={"sport": "soccer"},
        value_kind="name",
        raw_value="League",
        state="confirmed",
        valid_from="2022-01-01T00:00:00Z",
        valid_until="2023-01-01T00:00:00Z",
    )
    for team_id, tournament_id, raw in (
        (home_old.id, tournament_old.id, "Old Home"),
        (away_old.id, tournament_old.id, "Old Away"),
        (home_new.id, tournament_new.id, "New Home"),
        (away_new.id, tournament_new.id, "New Away"),
    ):
        registry.add_designation(
            entity_id=team_id,
            source="feed",
            kind="team",
            scope={"sport": "soccer", "tournament": tournament_id},
            value_kind="name",
            raw_value=raw,
            state="confirmed",
        )
    old_at = datetime(2020, 6, 1, 17, tzinfo=UTC)
    new_at = datetime(2022, 6, 1, 17, tzinfo=UTC)
    registry.set_event_relation(
        event_old.id,
        tournament_id=tournament_old.id,
        home_team_id=home_old.id,
        away_team_id=away_old.id,
        scheduled_at=old_at,
        actor="owner",
        reason="Старый турнир",
    )
    registry.set_event_relation(
        event_new.id,
        tournament_id=tournament_new.id,
        home_team_id=home_new.id,
        away_team_id=away_new.id,
        scheduled_at=new_at,
        actor="owner",
        reason="Новый турнир",
    )
    resolver = RegistryEventResolver(EventIdentitySnapshot.from_registry(registry))

    def resolve(at: datetime | None):
        return resolver.resolve(
            CanonicalEventRef(
                canonical_event_id=3,
                sport="soccer",
                tournament="League",
                source="feed",
                source_event_id="unmapped",
                scheduled_at=at,
                home_participant="Old Home" if at == old_at else "New Home",
                away_participant="Old Away" if at == old_at else "New Away",
            )
        )

    assert resolve(old_at).project_event_id == event_old.id
    assert resolve(new_at).project_event_id == event_new.id
    assert resolve(None).status == "ambiguous"
    assert resolve(datetime(2024, 6, 1, 17, tzinfo=UTC)).status == "unresolved"


def test_open_resolved_and_dismissed_overlays_apply_only_at_event_time(
    tmp_path: Path,
) -> None:
    registry, _, ref, event_a, tournament, _, away = make_fixture(tmp_path)
    relation_a = registry.get_event_relation(event_a.id)
    event_before = registry.create_entity("event", "Earlier same fixture", sport="soccer")
    registry.set_event_relation(
        event_before.id,
        tournament_id=tournament.id,
        home_team_id=relation_a.home_team_id,
        away_team_id=away.id,
        scheduled_at=datetime(2026, 9, 30, 17, tzinfo=UTC),
        actor="owner",
        reason="Событие до validity overlay",
    )
    event_b = registry.create_entity("event", "Same fixture alternate team", sport="soccer")
    team_b = registry.create_entity("team", "Alternate North", sport="soccer")
    registry.set_event_relation(
        event_b.id,
        tournament_id=tournament.id,
        home_team_id=team_b.id,
        away_team_id=away.id,
        scheduled_at=ref.scheduled_at,
        actor="owner",
        reason="Второй кандидат события",
    )
    start = "2026-10-01T00:00:00Z"
    until = "2026-11-01T00:00:00Z"
    overlay_designation = registry.add_designation(
        entity_id=team_b.id,
        source="fixture-feed",
        kind="team",
        scope={"sport": "soccer", "tournament": tournament.id},
        value_kind="name",
        raw_value="North",
        state="confirmed",
        valid_from=start,
        valid_until=until,
    )
    date_ref = CanonicalEventRef(
        **{
            **ref.__dict__,
            "source_event_id": "no-event-designation",
            "scheduled_at": datetime(2026, 10, 4, 17, tzinfo=UTC),
        }
    )
    before_ref = CanonicalEventRef(
        **{
            **date_ref.__dict__,
            "scheduled_at": datetime(2026, 9, 30, 17, tzinfo=UTC),
        }
    )

    open_snapshot = EventIdentitySnapshot.from_registry(registry)
    open_resolver = RegistryEventResolver(open_snapshot)
    assert open_resolver.resolve(date_ref).status == "conflict"
    assert open_resolver.resolve(replace(date_ref, scheduled_at=None)).status == "ambiguous"
    assert open_resolver.resolve(before_ref).project_event_id == event_before.id

    registry.decide_designation(
        overlay_designation.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="Выбрать альтернативную команду в этом периоде",
        expected_revision=overlay_designation.revision,
        conflict_period=(start, until),
    )
    resolved_snapshot = EventIdentitySnapshot.from_registry(registry)
    assert RegistryEventResolver(resolved_snapshot).resolve(date_ref).project_event_id == event_b.id
    assert (
        RegistryEventResolver(resolved_snapshot)
        .resolve(replace(date_ref, scheduled_at=None))
        .status
        == "ambiguous"
    )
    assert (
        RegistryEventResolver(resolved_snapshot).resolve(before_ref).project_event_id
        == event_before.id
    )

    updated = registry.get_designation(overlay_designation.id)
    registry.decide_designation(
        overlay_designation.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Отменить прежний периодический выбор",
        expected_revision=updated.revision,
    )
    dismissed_snapshot = EventIdentitySnapshot.from_registry(registry)
    dismissed_resolver = RegistryEventResolver(dismissed_snapshot)
    assert dismissed_resolver.resolve(date_ref).project_event_id == event_a.id
    assert dismissed_resolver.resolve(before_ref).project_event_id == event_before.id


def test_applying_changed_registry_content_under_same_snapshot_id_is_rejected(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    registry, snapshot, ref, first_event, tournament, home, away = make_fixture(
        tmp_path / "identity"
    )
    with Session(engine) as session:
        first_row = CanonicalEvent(
            sport=ref.sport,
            tournament=ref.tournament,
            source=ref.source,
            source_event_id=ref.source_event_id,
            scheduled_at=ref.scheduled_at,
            status="scheduled",
            current_revision_sha256="f" * 64,
            home_participant=ref.home_participant,
            away_participant=ref.away_participant,
        )
        session.add(first_row)
        session.flush()
        backfill_event_bridge(session, snapshot=snapshot, apply=True)
        original_id = first_row.id

        second_event = registry.create_entity("event", "North v South 2", sport="soccer")
        registry.add_designation(
            entity_id=second_event.id,
            source="fixture-feed",
            kind="event",
            scope={"sport": "soccer", "tournament": tournament.id},
            value_kind="external_id",
            raw_value="source-event-2",
            state="confirmed",
        )
        registry.set_event_relation(
            second_event.id,
            tournament_id=tournament.id,
            home_team_id=home.id,
            away_team_id=away.id,
            scheduled_at=ref.scheduled_at,
            actor="owner",
            reason="Новое событие после снимка",
        )
        changed_snapshot = EventIdentitySnapshot.from_registry(registry)
        assert changed_snapshot.snapshot_id != snapshot.snapshot_id
        forged_snapshot = replace(changed_snapshot, snapshot_id=snapshot.snapshot_id)
        second_row = CanonicalEvent(
            sport=ref.sport,
            tournament=ref.tournament,
            source=ref.source,
            source_event_id="source-event-2",
            scheduled_at=ref.scheduled_at,
            status="scheduled",
            current_revision_sha256="1" * 64,
            home_participant=ref.home_participant,
            away_participant=ref.away_participant,
        )
        session.add(second_row)
        session.flush()

        with pytest.raises(ValueError, match="(?i)snapshot.*content|содержим"):
            backfill_event_bridge(session, snapshot=forged_snapshot, apply=True)

        assert session.get(EventRegistryMapping, (snapshot.snapshot_id, original_id)) is not None
        assert session.get(EventRegistryMapping, (snapshot.snapshot_id, second_row.id)) is None
        assert first_event.id == snapshot.events[0].id
        reloaded = load_event_snapshot(session, snapshot_id=snapshot.snapshot_id)
        assert reloaded == snapshot
    engine.dispose()


def test_event_reader_compatibility_switch_is_off_by_default(tmp_path: Path) -> None:
    from sports_forecast.identity.events import registry_event_reader_enabled

    config = tmp_path / "identity_event.yaml"
    config.write_text("registry_event_reader_enabled: false\n", encoding="utf-8")

    assert registry_event_reader_enabled(config) is False
