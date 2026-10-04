"""Контракты атомарной установки полного registry snapshot на сервере."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.orm import Session

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity import installation as installation_module
from sports_forecast.identity.events import (
    CanonicalEventRef,
    EventRegistryMapping,
    load_installed_event_snapshot,
)
from sports_forecast.identity.installation import (
    InstalledRegistryReader,
    VerifiedPublicationRecord,
    pin_installed_registry,
)
from sports_forecast.identity.installation import (
    install_registry_publication as _install_registry_publication,
)
from sports_forecast.identity.publication import DownloadedPublication, PublicationRecord
from sports_forecast.identity.snapshot import export_registry_snapshot, verify_registry_snapshot
from sports_forecast.service.db.models import (
    ActiveRegistryInstallation,
    Base,
    CanonicalEvent,
    RegistryIdentitySnapshot,
    RegistryInstallationLock,
    RegistrySnapshotRecord,
)


def _fixture(tmp_path: Path):
    registry = EntityRegistry(tmp_path / "local.sqlite3")
    registry.initialize()
    league = registry.create_entity("tournament", "League", sport="hockey")
    registry.add_designation(
        entity_id=league.id,
        source="feed",
        kind="tournament",
        scope={"sport": "hockey"},
        value_kind="name",
        raw_value="League",
        state="confirmed",
    )
    return registry


def _event_fixture(tmp_path: Path, *, include_event_alias: bool = True):
    registry = _fixture(tmp_path)
    league = registry.list_entities(kind="tournament")[0]
    home = registry.create_entity("team", "North", sport="hockey")
    away = registry.create_entity("team", "South", sport="hockey")
    scope = {"sport": "hockey", "tournament": league.id}
    for entity, kind, value in (
        (home, "team", "North"),
        (away, "team", "South"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source="feed",
            kind=kind,
            scope=scope,
            value_kind="name",
            raw_value=value,
            state="confirmed",
        )
    event = registry.create_entity("event", "North vs South", sport="hockey")
    if include_event_alias:
        registry.add_designation(
            entity_id=event.id,
            source="feed",
            kind="event",
            scope=scope,
            value_kind="external_id",
            raw_value="event-1",
            state="confirmed",
        )
    start = datetime(2026, 10, 5, 17, tzinfo=UTC)
    registry.set_event_relation(
        event.id,
        tournament_id=league.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at=start,
        actor="owner",
        reason="fixture event relation",
    )
    return registry, event, start


def _engine():
    postgres_url = os.environ.get("SF_TEST_POSTGRES_URL")
    admin_engine = None
    if postgres_url:
        schema = f"task0265_{uuid4().hex[:16]}"
        admin_engine = create_engine(postgres_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            postgres_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )

        def drop_test_schema(_engine) -> None:
            assert admin_engine is not None
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin_engine.dispose()

        event.listen(engine, "engine_disposed", drop_test_schema, once=True)
    else:
        engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(RegistryInstallationLock(id=1, lock_version=0))
        session.commit()
    return engine


def install_registry_publication(
    session: Session,
    snapshot_path: Path,
    *,
    publication_sequence: int,
    publication_id: str,
    previous_publication_id: str | None = None,
):
    """Fixture для проверенной remote record с детерминированной UUID и временем."""
    snapshot = verify_registry_snapshot(snapshot_path)
    publication_uuid = str(uuid5(NAMESPACE_URL, publication_id))
    if previous_publication_id is None and publication_sequence > 1:
        previous_publication_id = f"pub-{publication_sequence - 1}"
    previous_uuid = (
        str(uuid5(NAMESPACE_URL, previous_publication_id))
        if previous_publication_id is not None
        else None
    )
    return _install_registry_publication(
        session,
        snapshot_path,
        publication=VerifiedPublicationRecord(
            publication_id=publication_uuid,
            sequence=publication_sequence,
            snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=snapshot.projection_sha256,
            previous_publication_id=previous_uuid,
            published_at=datetime(2026, 10, 4, 17, tzinfo=UTC),
            actor="owner.registry",
        ),
    )


def test_installation_is_idempotent_and_activates_new_sequence_for_old_snapshot(
    tmp_path: Path,
) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()

    with Session(engine) as session:
        first = install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        assert first.snapshot_id == artifact.snapshot_id
        assert pin_installed_registry(session).snapshot_id == artifact.snapshot_id

        repeated = install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        assert repeated.snapshot_id == artifact.snapshot_id

        rollback = install_registry_publication(
            session,
            artifact.path,
            publication_sequence=2,
            publication_id="pub-2",
        )
        session.commit()
        assert rollback.snapshot_id == artifact.snapshot_id
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None
        assert active.publication_sequence == 2

        reader = pin_installed_registry(session)
        assert isinstance(reader, InstalledRegistryReader)
        assert (
            reader.get_entity(registry.list_entities(kind="tournament")[0].id).project_name
            == "League"
        )
        assert len(session.scalars(select(RegistryIdentitySnapshot)).all()) == 1
    engine.dispose()


def test_installation_rejects_same_sequence_with_different_publication(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        with pytest.raises(ValueError, match="(?i)sequence|publication|публикац"):
            install_registry_publication(
                session,
                artifact.path,
                publication_sequence=1,
                publication_id="other-pub-1",
            )
    engine.dispose()


def test_failed_installation_leaves_previous_activation_unchanged(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        with pytest.raises(ValueError):
            install_registry_publication(
                session,
                artifact.path,
                publication_sequence=2,
                publication_id="pub-2",
                previous_publication_id="wrong-previous",
            )
        session.rollback()
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None
        assert active.publication_sequence == 1
    engine.dispose()


def test_installed_event_projection_and_bridge_are_pinned_to_ir1(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        canonical = CanonicalEvent(
            sport="hockey",
            tournament="Unknown League",
            source="feed",
            source_event_id="external-1",
            scheduled_at=datetime(2026, 10, 4, 17, tzinfo=UTC),
            status="scheduled",
            current_revision_sha256="a" * 64,
        )
        session.add(canonical)
        session.flush()
        installed = install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        event_snapshot = load_installed_event_snapshot(session, snapshot_id=artifact.snapshot_id)
        bridge = installed.get_event_mapping(canonical.id, session)
        assert event_snapshot.snapshot_id == artifact.snapshot_id
        assert event_snapshot.event_snapshot.snapshot_id.startswith("ev1:")
        result = event_snapshot.resolve(
            CanonicalEventRef(
                canonical_event_id=canonical.id,
                sport="hockey",
                tournament="Unknown League",
                source="feed",
                source_event_id="external-1",
                scheduled_at=canonical.scheduled_at,
                home_participant="Unknown Home",
                away_participant="Unknown Away",
            )
        )
        assert result.snapshot_id == artifact.snapshot_id
        assert bridge.snapshot_id == artifact.snapshot_id
        assert bridge.status == "unresolved"
    engine.dispose()


def test_event_relation_record_installs_and_reloads_under_full_ir1(tmp_path: Path) -> None:
    registry, event, start = _event_fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        canonical = CanonicalEvent(
            sport="hockey",
            tournament="League",
            source="feed",
            source_event_id="event-1",
            scheduled_at=start,
            status="scheduled",
            current_revision_sha256="b" * 64,
            home_participant="North",
            away_participant="South",
        )
        session.add(canonical)
        session.flush()
        installed = install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        reloaded = load_installed_event_snapshot(session, snapshot_id=artifact.snapshot_id)
        mapping = installed.get_event_mapping(canonical.id, session)
        assert reloaded.event_snapshot.events[0].id == event.id
        assert mapping.status == "resolved"
        assert mapping.project_event_id == event.id
    engine.dispose()


def test_late_duplicate_canonical_event_does_not_rewrite_mapping_on_next_publication(
    tmp_path: Path,
) -> None:
    registry, event, start = _event_fixture(tmp_path, include_event_alias=False)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        first_event = CanonicalEvent(
            sport="hockey",
            tournament="League",
            source="feed",
            source_event_id="event-1",
            scheduled_at=start,
            status="scheduled",
            current_revision_sha256="c" * 64,
            home_participant="North",
            away_participant="South",
        )
        session.add(first_event)
        session.flush()
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        pinned_mapping = session.get(EventRegistryMapping, (artifact.snapshot_id, first_event.id))
        assert pinned_mapping is not None
        assert pinned_mapping.status == "resolved"
        assert pinned_mapping.project_event_id == event.id

        competitor = CanonicalEvent(
            sport="hockey",
            tournament="League",
            source="feed",
            source_event_id="event-duplicate",
            scheduled_at=start,
            status="scheduled",
            current_revision_sha256="d" * 64,
            home_participant="North",
            away_participant="South",
        )
        session.add(competitor)
        session.flush()
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=2,
            publication_id="pub-2",
        )
        session.commit()

        first_mapping = session.get(EventRegistryMapping, (artifact.snapshot_id, first_event.id))
        assert first_mapping is not None
        assert first_mapping.status == "resolved"
        late_mapping = session.get(EventRegistryMapping, (artifact.snapshot_id, competitor.id))
        assert late_mapping is not None
        assert late_mapping.status == "ambiguous"
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None
        assert active.publication_sequence == 2
    engine.dispose()


def test_pinned_reader_keeps_its_generation_after_activation_switch(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    first = export_registry_snapshot(registry, tmp_path / "packages")
    league_id = registry.list_entities(kind="tournament")[0].id
    registry.rename_entity(league_id, "Renamed League")
    second = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        first_reader = install_registry_publication(
            session,
            first.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        assert pin_installed_registry(session).snapshot_id == first.snapshot_id
        second_reader = install_registry_publication(
            session,
            second.path,
            publication_sequence=2,
            publication_id="pub-2",
        )
        session.commit()
        assert pin_installed_registry(session).snapshot_id == second.snapshot_id
        rollback_reader = install_registry_publication(
            session,
            first.path,
            publication_sequence=3,
            publication_id="pub-3",
        )
        session.commit()
        active_reader = pin_installed_registry(session)
        assert active_reader.snapshot_id == first.snapshot_id
        assert first_reader.get_entity(league_id).project_name == "League"
        assert second_reader.get_entity(league_id).project_name == "Renamed League"
        assert rollback_reader.get_entity(league_id).project_name == "League"
        assert first_reader.snapshot_id == first.snapshot_id
        assert second_reader.snapshot_id == second.snapshot_id
    engine.dispose()


def test_database_projection_failure_rolls_back_staging_and_keeps_active_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _fixture(tmp_path)
    first = export_registry_snapshot(registry, tmp_path / "packages")
    registry.rename_entity(registry.list_entities(kind="tournament")[0].id, "League 2")
    second = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        install_registry_publication(
            session,
            first.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        actual_install = installation_module._install_event_bridge

        def fail_after_staging(session_arg, snapshot_arg):
            actual_install(session_arg, snapshot_arg)
            raise ValueError("injected bridge integrity failure")

        monkeypatch.setattr(installation_module, "_install_event_bridge", fail_after_staging)
        with pytest.raises(ValueError, match="injected"):
            install_registry_publication(
                session,
                second.path,
                publication_sequence=2,
                publication_id="pub-2",
            )
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None
        assert active.snapshot_id == first.snapshot_id
        assert session.get(RegistryIdentitySnapshot, second.snapshot_id) is None
    engine.dispose()


def test_rolled_back_installation_is_not_exposed_from_snapshot_cache(tmp_path: Path) -> None:
    registry, _event, _start = _event_fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as writer:
        install_registry_publication(
            writer,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        assert pin_installed_registry(writer).snapshot_id == artifact.snapshot_id
        writer.rollback()

    with Session(engine) as reader:
        assert reader.get(RegistryIdentitySnapshot, artifact.snapshot_id) is None
        with pytest.raises(KeyError):
            load_installed_event_snapshot(reader, snapshot_id=artifact.snapshot_id)
    engine.dispose()


def test_installed_rows_are_rechecked_on_each_pinned_read(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()
        row = session.scalars(
            select(RegistrySnapshotRecord).where(
                RegistrySnapshotRecord.__table__.c.snapshot_id == artifact.snapshot_id
            )
        ).first()
        assert row is not None
        session.execute(
            update(RegistrySnapshotRecord)
            .where(
                RegistrySnapshotRecord.__table__.c.snapshot_id == row.snapshot_id,
                RegistrySnapshotRecord.__table__.c.file_name == row.file_name,
                RegistrySnapshotRecord.__table__.c.record_key == row.record_key,
            )
            .values(payload_json="{}")
        )
        session.commit()
        with pytest.raises(ValueError, match="(?i)manifest|record key|records|стабильного key"):
            pin_installed_registry(session)
    engine.dispose()


def test_pinned_snapshot_cache_avoids_reloading_records_and_is_engine_scoped(
    tmp_path: Path,
) -> None:
    registry = _fixture(tmp_path)
    artifact = export_registry_snapshot(registry, tmp_path / "packages")
    engine = _engine()
    with Session(engine) as session:
        install_registry_publication(
            session,
            artifact.path,
            publication_sequence=1,
            publication_id="pub-1",
        )
        session.commit()

    record_selects: list[str] = []

    def count_record_queries(_conn, _cursor, statement, _params, _context, _executemany):
        if "registry_snapshot_records" in statement:
            record_selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_record_queries)
    try:
        with Session(engine) as first_session:
            first = pin_installed_registry(first_session)
        first_count = len(record_selects)
        assert first_count > 0

        with Session(engine) as second_session:
            second = pin_installed_registry(second_session)
        assert second.snapshot_id == first.snapshot_id
        assert len(record_selects) == first_count
    finally:
        event.remove(engine, "before_cursor_execute", count_record_queries)

    other_engine = _engine()
    with Session(other_engine) as other_session, pytest.raises(KeyError):
        load_installed_event_snapshot(other_session, snapshot_id=artifact.snapshot_id)
    other_engine.dispose()
    engine.dispose()


def test_verified_publication_factory_preserves_validated_remote_record(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    snapshot = export_registry_snapshot(registry, tmp_path / "packages")
    record = PublicationRecord(
        publication_id=str(uuid5(NAMESPACE_URL, "pub-1")),
        sequence=1,
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=snapshot.projection_sha256,
        previous_publication_id=None,
        published_at="2026-10-04T17:00:00Z",
        actor="owner.registry",
    )
    verified = VerifiedPublicationRecord.from_downloaded(
        DownloadedPublication(record=record, snapshot_path=snapshot.path)
    )
    assert verified.snapshot_id == snapshot.snapshot_id
    offset = verified.published_at.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
