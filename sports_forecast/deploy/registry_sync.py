"""Серверная установка цепочки опубликованных registry snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sports_forecast.identity.installation import (
    VerifiedPublicationRecord,
    install_registry_publication,
    pin_installed_registry,
)
from sports_forecast.identity.publication import (
    DownloadedPublication,
    PublicationRecord,
    Storage,
    download_publication_snapshot,
    read_current_publication,
    read_publication_by_id,
)
from sports_forecast.service.db.models import ActiveRegistryInstallation


class RegistrySyncError(RuntimeError):
    """Опубликованная цепочка не может быть безопасно установлена."""


@dataclass(frozen=True)
class RegistrySyncResult:
    """Установленная publication и число применённых records."""

    publication_sequence: int
    publication_id: str
    snapshot_id: str
    applied_publications: int


def _active_identity(engine: Engine) -> tuple[int, str] | None:
    with Session(engine) as session:
        active = session.get(ActiveRegistryInstallation, 1)
        if active is None:
            return None
        return active.publication_sequence, active.publication_id


def _pending_chain(
    storage: Storage,
    *,
    prefix: str,
    current: PublicationRecord,
    active: tuple[int, str] | None,
    max_chain_length: int,
    deadline: float,
) -> list[PublicationRecord]:
    """Пройти immutable previous links от закреплённого current до active."""
    if active is not None and current.sequence < active[0]:
        raise RegistrySyncError("Object Storage current старее установленной publication")
    chain: list[PublicationRecord] = []
    record = current
    while active is None or record.sequence > active[0]:
        if monotonic() > deadline or len(chain) >= max_chain_length:
            raise RegistrySyncError("Registry catch-up превысил лимит времени или публикаций")
        chain.append(record)
        if record.sequence == 1:
            if active is not None:
                raise RegistrySyncError("Remote publication chain не достигает active version")
            break
        previous_id = record.previous_publication_id
        if previous_id is None:
            raise RegistrySyncError("Remote publication chain оборвана")
        previous = read_publication_by_id(storage, prefix=prefix, publication_id=previous_id)
        if previous.sequence != record.sequence - 1:
            raise RegistrySyncError("Remote publication sequence не непрерывна")
        record = previous
    if active is not None and (record.sequence, record.publication_id) != active:
        raise RegistrySyncError("Remote publication chain расходится с active version")
    chain.reverse()
    return chain


def sync_current_registry(
    storage: Storage,
    engine: Engine,
    *,
    prefix: str,
    download_root: Path,
    max_chain_length: int = 100,
    max_download_bytes: int = 2 * 1024 * 1024 * 1024,
    max_duration_seconds: float = 300.0,
) -> RegistrySyncResult:
    """Скачать pinned current, проверить цепочку и атомарно установить её в БД.

    Сеть используется до транзакции записи. Если любая установка не прошла,
    вся цепочка откатывается, а прежняя active publication остаётся доступной.
    """
    if max_chain_length < 1 or max_download_bytes < 1 or max_duration_seconds <= 0:
        raise ValueError("Registry sync budgets должны быть положительными")
    deadline = monotonic() + max_duration_seconds
    current = read_current_publication(storage, prefix=prefix)
    observed_active = _active_identity(engine)
    pending = _pending_chain(
        storage,
        prefix=prefix,
        current=current,
        active=observed_active,
        max_chain_length=max_chain_length,
        deadline=deadline,
    )
    downloads: list[DownloadedPublication] = []
    downloaded_bytes = 0
    for record in pending:
        if monotonic() > deadline:
            raise RegistrySyncError("Registry catch-up превысил лимит времени")
        remaining_bytes = max_download_bytes - downloaded_bytes
        if remaining_bytes < 1:
            raise RegistrySyncError("Registry catch-up превысил лимит байтов")
        path = download_publication_snapshot(
            storage,
            prefix=prefix,
            publication_id=record.publication_id,
            destination=Path(download_root),
            max_bytes=remaining_bytes,
        )
        downloaded_bytes += sum(item.stat().st_size for item in path.iterdir() if item.is_file())
        if downloaded_bytes > max_download_bytes:
            raise RegistrySyncError("Registry catch-up превысил лимит байтов")
        if (
            read_publication_by_id(storage, prefix=prefix, publication_id=record.publication_id)
            != record
        ):
            raise RegistrySyncError("Publication record изменился во время download")
        downloads.append(DownloadedPublication(record=record, snapshot_path=path))
    with Session(engine) as session, session.begin():
        active = session.get(ActiveRegistryInstallation, 1)
        actual_active = (
            (active.publication_sequence, active.publication_id) if active is not None else None
        )
        if actual_active != observed_active:
            raise RegistrySyncError("Active publication изменилась во время sync")
        for downloaded in downloads:
            if monotonic() > deadline:
                raise RegistrySyncError("Registry catch-up превысил лимит времени")
            install_registry_publication(
                session,
                downloaded.snapshot_path,
                publication=VerifiedPublicationRecord.from_downloaded(downloaded),
            )
        pinned = pin_installed_registry(session)
        if (
            pinned.publication_sequence != current.sequence
            or pinned.publication_id != current.publication_id
            or pinned.snapshot_id != current.snapshot_id
        ):
            raise RegistrySyncError("Установленная publication не соответствует pinned current")
        return RegistrySyncResult(
            publication_sequence=pinned.publication_sequence,
            publication_id=pinned.publication_id,
            snapshot_id=pinned.snapshot_id,
            applied_publications=len(downloads),
        )
