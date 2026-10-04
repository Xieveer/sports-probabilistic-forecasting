"""Сквозной capture новых source aliases при установленном registry."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.data.providers.odds.client import OddsApiQuotaSnapshot
from sports_forecast.data.providers.odds.team_name_registry import TeamNameRegistry
from sports_forecast.deploy import canonical_bootstrap
from sports_forecast.deploy.registry_sync import sync_current_registry
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.feedback import import_pending_candidate_batches
from sports_forecast.identity.installation import (
    VerifiedPublicationRecord,
    install_registry_publication,
    pin_installed_registry,
)
from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    RegistryPublisher,
    StorageObject,
)
from sports_forecast.identity.review_service import CandidateDecision, ReviewQueueService
from sports_forecast.identity.snapshot import export_registry_snapshot
from sports_forecast.orchestration.future_odds import run_nhl_future_odds_batch
from sports_forecast.service.db.models import (
    Base,
    CanonicalEvent,
    DataCycleRun,
    OddsObservation,
    RegistryCandidateOutbox,
    RegistryInstallationLock,
)
from sports_forecast.service.db.registry_feedback import RegistryCandidateFeedback
from sports_forecast.service.odds_projection import sync_odds_store_observations
from sports_forecast.service.registry_candidate_capture import enqueue_unresolved_canonical_event


def test_new_nhl_canonical_event_keeps_calendar_and_queues_tournament(
    tmp_path: Path, monkeypatch
) -> None:
    """Unknown source alias не препятствует canonical import и ждёт владельца."""
    local_registry = EntityRegistry(tmp_path / "registry.sqlite3")
    local_registry.initialize()
    snapshot = export_registry_snapshot(local_registry, tmp_path / "snapshot")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    source_csv = tmp_path / "source.csv"
    source_csv.write_text(
        "id,datetime,match_is_end,home_team,away_team\nm1,2026-10-05T17:00:00Z,0,North,South\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", "11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(canonical_bootstrap, "registry_event_reader_enabled", lambda: True)
    try:
        with Session(engine) as session:
            session.add(RegistryInstallationLock(id=1, lock_version=0))
            session.flush()
            install_registry_publication(
                session,
                snapshot.path,
                publication=VerifiedPublicationRecord(
                    publication_id=str(uuid4()),
                    sequence=1,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_sha256=snapshot.projection_sha256,
                    previous_publication_id=None,
                    published_at=datetime(2026, 10, 4, 17, tzinfo=UTC),
                    actor="owner.registry",
                ),
            )
            session.commit()
            summary = canonical_bootstrap.refresh_nhl_canonical_with_summary_from_csv(
                source_csv, session
            )
            assert summary.new_events == 1
            assert session.scalar(select(CanonicalEvent)) is not None
            candidates = session.scalars(select(RegistryCandidateOutbox)).all()
            assert len(candidates) == 1
            assert '"kind":"tournament"' in candidates[0].payload_json
            assert '"raw_value":"nhl"' in candidates[0].payload_json
    finally:
        engine.dispose()


def test_football_feedback_snapshot_unlocks_confirmed_odds(tmp_path: Path, monkeypatch) -> None:
    """Второй турнир проходит ту же очередь, решение и повторную публикацию."""
    from sports_forecast.service import odds_projection

    installation_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", installation_id)
    monkeypatch.setattr(odds_projection, "registry_event_reader_enabled", lambda: True)
    registry = EntityRegistry(tmp_path / "football.sqlite3")
    registry.initialize()
    league = registry.create_entity("tournament", "Premier League", sport="football")
    home = registry.create_entity("team", "Arsenal", sport="football")
    away = registry.create_entity("team", "Chelsea", sport="football")
    match = registry.create_entity("event", "Arsenal vs Chelsea", sport="football")
    scope = {"sport": "football", "tournament": league.id}
    registry.add_designation(
        entity_id=league.id,
        source="fixture_feed",
        kind="tournament",
        scope={"sport": "football"},
        value_kind="name",
        raw_value="epl",
        state="confirmed",
    )
    for entity, raw in ((home, "ARS"), (away, "CHE")):
        registry.add_designation(
            entity_id=entity.id,
            source="fixture_feed",
            kind="team",
            scope=scope,
            value_kind="name",
            raw_value=raw,
            state="confirmed",
        )
    registry.add_designation(
        entity_id=home.id,
        source="the_odds_api",
        kind="team",
        scope=scope,
        value_kind="name",
        raw_value="Arsenal FC",
        state="confirmed",
    )
    registry.add_designation(
        entity_id=match.id,
        source="fixture_feed",
        kind="event",
        scope=scope,
        value_kind="external_id",
        raw_value="fixture-1",
        state="confirmed",
    )
    kickoff = datetime(2026, 10, 5, 19, tzinfo=UTC)
    registry.set_event_relation(
        match.id,
        tournament_id=league.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=kickoff,
        actor="owner",
        reason="fixture",
    )
    storage = _MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "football.lock", actor="owner"
    )
    first = export_registry_snapshot(registry, tmp_path / "football-snapshots")
    publisher.publish(first.path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(RegistryInstallationLock(id=1, lock_version=0))
        session.add(
            CanonicalEvent(
                sport="football",
                tournament="epl",
                source="fixture_feed",
                source_event_id="fixture-1",
                scheduled_at=kickoff.replace(tzinfo=None),
                status="scheduled",
                current_revision_sha256="b" * 64,
                home_participant="ARS",
                away_participant="CHE",
            )
        )
        session.commit()
    policy = {
        "odds_markets": [
            {
                "market": "winner",
                "market_spec": "1x2",
                "bookmaker": "pinnacle",
                "value_columns": ["home_close", "draw_close", "away_close"],
                "provider_timestamp_column": "provider_observed_at",
            }
        ]
    }
    frame = pd.DataFrame(
        [
            {
                "home_team_norm": "Arsenal FC",
                "away_team_norm": "Chelsea FC",
                "commence_time_utc": kickoff.isoformat(),
                "fetched_at": "2026-10-04T12:00:00Z",
                "provider_observed_at": "2026-10-04T12:00:00Z",
                "home_close": 2.1,
                "draw_close": 3.2,
                "away_close": 3.6,
            }
        ]
    )
    try:
        sync_current_registry(
            storage,
            engine,
            prefix="entity-registry/v1",
            download_root=tmp_path / "football-downloads",
        )
        with Session(engine) as session:
            assert (
                sync_odds_store_observations(session, "epl", frame, policy, TeamNameRegistry()) == 0
            )
            assert session.scalar(select(OddsObservation)) is None
            feedback = RegistryCandidateFeedback(
                session, storage, prefix="entity-registry/v1", installation_id=installation_id
            )
            assert feedback.publish_next_batch() is not None
        imported = import_pending_candidate_batches(
            storage, registry, prefix="entity-registry/v1", installation_id=installation_id
        )
        assert imported.imported_candidates == 1
        candidate = ReviewQueueService(registry).list_candidates(source="the_odds_api")[0]
        assert candidate.raw_value == "Chelsea FC"
        ReviewQueueService(registry).decide_batch(
            [
                CandidateDecision(
                    candidate_id=candidate.id,
                    expected_revision=candidate.revision,
                    expected_designation_revision=candidate.designation_revision,
                    action="confirm",
                    entity_id=away.id,
                    reason="Проверено владельцем",
                )
            ],
            actor="owner",
        )
        second = export_registry_snapshot(registry, tmp_path / "football-snapshots")
        assert second.snapshot_id != first.snapshot_id
        publisher.publish(second.path)
        sync_current_registry(
            storage,
            engine,
            prefix="entity-registry/v1",
            download_root=tmp_path / "football-downloads",
        )
        with Session(engine) as session:
            assert (
                sync_odds_store_observations(session, "epl", frame, policy, TeamNameRegistry()) == 1
            )
            line = session.scalar(select(OddsObservation))
            assert line is not None
            assert line.registry_snapshot_id == second.snapshot_id
    finally:
        engine.dispose()


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        if key not in self.objects:
            raise FileNotFoundError(key)
        body = self.objects[key]
        if max_bytes is not None and len(body) > max_bytes:
            raise ValueError("storage byte limit")
        return StorageObject(body, hashlib.md5(body, usedforsecurity=False).hexdigest())

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        prior = self.objects.get(key)
        if if_none_match and prior is not None:
            raise ConditionalWriteConflictError("exists")
        if if_match is not None and (
            prior is None or hashlib.md5(prior, usedforsecurity=False).hexdigest() != if_match
        ):
            raise ConditionalWriteConflictError("changed")
        self.objects[key] = body
        return hashlib.md5(body, usedforsecurity=False).hexdigest()

    def list_keys(
        self,
        prefix: str,
        *,
        continuation_token: str | None = None,
        start_after: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[tuple[str, ...], str | None]:
        keys = tuple(
            sorted(
                key
                for key in self.objects
                if key.startswith(prefix) and (start_after is None or key > start_after)
            )
        )
        start = int(continuation_token or 0)
        page = keys[start : start + max_keys]
        next_token = str(start + len(page)) if start + len(page) < len(keys) else None
        return page, next_token


class _OddsProvider:
    def fetch_future_nhl_odds(self, **_kwargs):
        return [
            {
                "id": "odds-1",
                "commence_time": "2026-10-05T17:00:00Z",
                "home_team": "North Stars",
                "away_team": "South Stars",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "last_update": "2026-10-04T12:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "North Stars", "price": 2.0},
                                    {"name": "South Stars", "price": 1.9},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    def last_quota(self) -> OddsApiQuotaSnapshot:
        return OddsApiQuotaSnapshot(None, None)


def test_owner_decision_republished_snapshot_unlocks_odds(tmp_path: Path, monkeypatch) -> None:
    """Server outbox → local decision → новый ir1 → подтверждённая линия."""
    from sports_forecast.orchestration import future_odds

    installation_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", installation_id)
    monkeypatch.setattr(future_odds, "registry_event_reader_enabled", lambda: True)
    registry = EntityRegistry(tmp_path / "local.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    home = registry.create_entity("team", "North", sport="ice_hockey")
    away = registry.create_entity("team", "South", sport="ice_hockey")
    project_event = registry.create_entity("event", "North vs South", sport="ice_hockey")
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    registry.add_designation(
        entity_id=tournament.id,
        source="nhl_web_api",
        kind="tournament",
        scope={"sport": "ice_hockey"},
        value_kind="name",
        raw_value="nhl",
        state="confirmed",
    )
    for source, entity, raw in (
        ("nhl_web_api", home, "NTH"),
        ("nhl_web_api", away, "STH"),
        ("the_odds_api", home, "North Stars"),
        ("the_odds_api", away, "South Stars"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source=source,
            kind="team",
            scope=scope,
            value_kind="name",
            raw_value=raw,
            state="confirmed",
        )
    registry.add_designation(
        entity_id=project_event.id,
        source="nhl_web_api",
        kind="event",
        scope=scope,
        value_kind="external_id",
        raw_value="m1",
        state="confirmed",
    )
    kickoff = datetime(2026, 10, 5, 17, tzinfo=UTC)
    registry.set_event_relation(
        project_event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=kickoff,
        actor="owner",
        reason="fixture",
    )
    storage = _MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "publish.lock", actor="owner"
    )
    first = export_registry_snapshot(registry, tmp_path / "snapshots")
    publisher.publish(first.path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(RegistryInstallationLock(id=1, lock_version=0))
        session.add(
            CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="m1",
                scheduled_at=kickoff.replace(tzinfo=None),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="NTH",
                away_participant="STH",
            )
        )
        session.add(
            DataCycleRun(run_id="run-1", tournament="nhl", reason="scheduled", status="running")
        )
        session.commit()
    try:
        sync_current_registry(
            storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
        )
        team_registry = TeamNameRegistry.from_source_sections(
            {"NTH": "NTH", "STH": "STH"},
            {"NORTHSTARS": "NTH", "SOUTHSTARS": "STH"},
        )
        with Session(engine) as session:
            first_attempt = run_nhl_future_odds_batch(
                session,
                run_id="run-1",
                now=datetime(2026, 10, 4, 12, tzinfo=UTC),
                provider=_OddsProvider(),
                team_registry=team_registry,
                clock=lambda: datetime(2026, 10, 4, 12, tzinfo=UTC),
            )
            assert first_attempt.matched_events == 0
            assert session.scalar(select(OddsObservation)) is None
            assert session.scalar(select(RegistryCandidateOutbox)) is not None
            feedback = RegistryCandidateFeedback(
                session, storage, prefix="entity-registry/v1", installation_id=installation_id
            )
            assert feedback.publish_next_batch() is not None
        imported = import_pending_candidate_batches(
            storage, registry, prefix="entity-registry/v1", installation_id=installation_id
        )
        assert imported.imported_candidates == 1
        candidate = ReviewQueueService(registry).list_candidates(source="the_odds_api")[0]
        assert candidate.kind == "tournament"
        ReviewQueueService(registry).decide_batch(
            [
                CandidateDecision(
                    candidate_id=candidate.id,
                    expected_revision=candidate.revision,
                    expected_designation_revision=candidate.designation_revision,
                    action="confirm",
                    entity_id=tournament.id,
                    reason="Проверено владельцем",
                )
            ],
            actor="owner",
        )
        second = export_registry_snapshot(registry, tmp_path / "snapshots")
        assert second.snapshot_id != first.snapshot_id
        publisher.publish(second.path)
        sync_current_registry(
            storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
        )
        with Session(engine) as session:
            first_run = session.scalar(
                select(DataCycleRun).where(DataCycleRun.__table__.c.run_id == "run-1")
            )
            assert first_run is not None
            first_run.status = "success"
            session.flush()
            session.add(
                DataCycleRun(run_id="run-2", tournament="nhl", reason="scheduled", status="running")
            )
            session.flush()
            second_attempt = run_nhl_future_odds_batch(
                session,
                run_id="run-2",
                now=datetime(2026, 10, 4, 12, tzinfo=UTC),
                provider=_OddsProvider(),
                team_registry=team_registry,
                clock=lambda: datetime(2026, 10, 4, 12, tzinfo=UTC),
            )
            observation = session.scalar(select(OddsObservation))
            assert second_attempt.matched_events == 1
            assert observation is not None
            assert observation.registry_snapshot_id == second.snapshot_id
            canonical = session.scalar(select(CanonicalEvent))
            assert canonical is not None
            canonical.home_participant = "STH"
            session.flush()
            reader = pin_installed_registry(session)
            stale = reader.get_event_mapping(int(canonical.id), session)
            assert stale.status == "conflict"
            assert stale.project_event_id is None
            assert (
                enqueue_unresolved_canonical_event(
                    session,
                    reader,
                    canonical,
                    stale,
                    observed_at=datetime(2026, 10, 4, 13, tzinfo=UTC),
                )
                == 1
            )
            conflicts = session.scalars(select(RegistryCandidateOutbox)).all()
            assert any("Изменившиеся участники" in row.payload_json for row in conflicts)
    finally:
        engine.dispose()
