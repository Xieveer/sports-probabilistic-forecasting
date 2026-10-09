"""Серверный sync устанавливает проверенную цепочку публикаций атомарно."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.deploy import registry_sync
from sports_forecast.deploy.registry_sync import sync_current_registry
from sports_forecast.deploy.registry_sync_cli import main as sync_main
from sports_forecast.identity.installation import (
    InstalledRegistryReader,
    VerifiedPublicationRecord,
)
from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    PublicationError,
    RegistryPublisher,
    StorageObject,
)
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.snapshot import export_registry_snapshot
from sports_forecast.service.db.models import (
    ActiveRegistryInstallation,
    Base,
    RegistryInstallationLock,
)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.corrupt_key: str | None = None
        self.get_calls: list[str] = []

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        self.get_calls.append(key)
        try:
            body, etag = self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc
        if key == self.corrupt_key:
            body += b"corrupt"
        if max_bytes is not None and len(body) > max_bytes:
            raise PublicationError("Object Storage bytes превышают лимит байтов")
        return StorageObject(body, etag)

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        prior = self.objects.get(key)
        if (
            if_none_match
            and prior is not None
            or if_match
            and (prior is None or prior[1] != if_match)
        ):
            raise ConditionalWriteConflictError("CAS mismatch")
        etag = hashlib.sha256(body).hexdigest()
        self.objects[key] = (body, etag)
        return etag


def _packages(tmp_path: Path) -> tuple[Path, Path, str]:
    registry = EntityRegistry(tmp_path / "local.sqlite3")
    registry.initialize()
    league = registry.create_entity("tournament", "League", sport="hockey")
    first = export_registry_snapshot(registry, tmp_path / "packages").path
    registry.rename_entity(league.id, "Renamed League")
    second = export_registry_snapshot(registry, tmp_path / "packages").path
    return first, second, league.id


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(RegistryInstallationLock(id=1, lock_version=0))
        session.commit()
    return engine


def test_sync_replays_missing_chain_and_pins_latest_snapshot(tmp_path: Path) -> None:
    first, second, _league_id = _packages(tmp_path)
    storage = MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "publish.lock", actor="owner"
    )
    initial = publisher.publish(first)
    latest = publisher.publish(second)
    engine = _engine()

    result = sync_current_registry(
        storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
    )

    assert result.publication_sequence == 2
    assert result.applied_publications == 2
    assert result.snapshot_id == latest.snapshot_id
    repeated = sync_current_registry(
        storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
    )
    assert repeated.applied_publications == 0
    rollback = publisher.publish(first)
    rolled_back = sync_current_registry(
        storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
    )
    assert rolled_back.publication_sequence == 3
    assert rolled_back.applied_publications == 1
    assert rolled_back.snapshot_id == initial.snapshot_id
    with Session(engine) as session:
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None and active.publication_id == rollback.publication_id
    engine.dispose()


def test_failed_later_download_keeps_previous_installed_generation(tmp_path: Path) -> None:
    first, second, _league_id = _packages(tmp_path)
    storage = MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "publish.lock", actor="owner"
    )
    initial = publisher.publish(first)
    engine = _engine()
    sync_current_registry(
        storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
    )
    latest = publisher.publish(second)
    storage.corrupt_key = f"entity-registry/v1/snapshots/{latest.snapshot_sha256}/entities.jsonl"

    with pytest.raises(RuntimeError, match="Remote snapshot file"):
        sync_current_registry(
            storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
        )

    with Session(engine) as session:
        active = session.get(ActiveRegistryInstallation, 1)
        assert active is not None
        assert active.publication_id == initial.publication_id
        assert active.publication_sequence == 1
    engine.dispose()


def test_failure_during_second_install_rolls_back_whole_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, _league_id = _packages(tmp_path)
    storage = MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "publish.lock", actor="owner"
    )
    publisher.publish(first)
    publisher.publish(second)
    engine = _engine()

    actual_install = registry_sync.install_registry_publication
    attempts = 0

    def fail_second(
        session: Session, snapshot_path: Path, *, publication: VerifiedPublicationRecord
    ) -> InstalledRegistryReader:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("second installation failed")
        return actual_install(session, snapshot_path, publication=publication)

    monkeypatch.setattr(registry_sync, "install_registry_publication", fail_second)
    with pytest.raises(RuntimeError, match="second installation failed"):
        sync_current_registry(
            storage, engine, prefix="entity-registry/v1", download_root=tmp_path / "downloads"
        )
    with Session(engine) as session:
        assert session.get(ActiveRegistryInstallation, 1) is None
    engine.dispose()


def test_sync_cli_rejects_implicit_sqlite_without_creating_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)

    assert sync_main(["--download-root", str(tmp_path / "downloads")]) == 1
    assert not (tmp_path / "predictions.db").exists()


def test_catch_up_budget_failure_keeps_active_version(tmp_path: Path) -> None:
    first, second, _league_id = _packages(tmp_path)
    storage = MemoryStorage()
    publisher = RegistryPublisher(
        storage, prefix="entity-registry/v1", lock_path=tmp_path / "publish.lock", actor="owner"
    )
    publisher.publish(first)
    publisher.publish(second)
    storage.get_calls.clear()
    engine = _engine()

    with pytest.raises(RuntimeError, match="лимит времени или публикаций"):
        sync_current_registry(
            storage,
            engine,
            prefix="entity-registry/v1",
            download_root=tmp_path / "downloads",
            max_chain_length=1,
        )

    with Session(engine) as session:
        assert session.get(ActiveRegistryInstallation, 1) is None
    with pytest.raises(RuntimeError, match="лимит байтов"):
        sync_current_registry(
            storage,
            engine,
            prefix="entity-registry/v1",
            download_root=tmp_path / "downloads",
            max_download_bytes=1,
        )
    snapshot_reads = [key for key in storage.get_calls if "/snapshots/" in key]
    assert len(snapshot_reads) == 1 and snapshot_reads[0].endswith("/manifest.json")
    with Session(engine) as session:
        assert session.get(ActiveRegistryInstallation, 1) is None
    engine.dispose()
