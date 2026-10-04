"""Установка и чтение закреплённого server-side registry snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal, Self, cast
from uuid import UUID

from sqlalchemy import event, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from sports_forecast.identity.events import (
    CanonicalEventRef,
    EventIdentitySnapshot,
    EventRegistryMapping,
    EventResolution,
    RegistryEventResolver,
    _parse_utc,
    _validate_snapshot,
)
from sports_forecast.identity.registry import Entity, EntityKind, EntityRegistry, Resolution
from sports_forecast.identity.snapshot import (
    SNAPSHOT_FORMAT_VERSION,
    RegistrySnapshotReader,
    VerifiedRegistrySnapshot,
    verify_registry_snapshot,
)
from sports_forecast.service.db.models import (
    ActiveRegistryInstallation,
    CanonicalEvent,
    RegistryEventResolverProjection,
    RegistryIdentitySnapshot,
    RegistryInstallationLock,
    RegistryPublication,
    RegistrySnapshotRecord,
)


if TYPE_CHECKING:
    from sports_forecast.identity.publication import DownloadedPublication


_RECORD_FILES = (
    "entities.jsonl",
    "designations.jsonl",
    "decisions.jsonl",
    "events.jsonl",
    "memberships.jsonl",
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SNAPSHOT_CACHE_MAX_BYTES = 128 * 1024 * 1024
_SNAPSHOT_CACHE_MAX_ENTRIES = 4


@dataclass(frozen=True)
class _SnapshotCacheEntry:
    snapshot: VerifiedRegistrySnapshot
    entity_reader: RegistrySnapshotReader
    footprint: int


_SNAPSHOT_CACHE: OrderedDict[tuple[Engine, str], _SnapshotCacheEntry] = OrderedDict()
_SNAPSHOT_CACHE_BYTES = 0
_SNAPSHOT_CACHE_LOCK = RLock()
_UNCOMMITTED_SNAPSHOT_IDS = "_registry_uncommitted_snapshot_ids"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _record_key(file_name: str, row: dict[str, Any]) -> str:
    key_fields = {
        "entities.jsonl": ("id",),
        "designations.jsonl": ("id",),
        "decisions.jsonl": ("id", "seed_key"),
        "events.jsonl": ("event_id",),
        "memberships.jsonl": ("id",),
    }
    fields = key_fields.get(file_name)
    if fields is None:
        raise ValueError(f"Неизвестный snapshot record type: {file_name}")
    key = next((row[field] for field in fields if row.get(field) is not None), None)
    if key is None:
        raise ValueError(f"Snapshot record не имеет стабильного key: {file_name}")
    if file_name in {"designations.jsonl", "decisions.jsonl"}:
        key = f"{row.get('record_type')}:{key}"
    value = str(key)
    if not value or len(value) > 256:
        raise ValueError(f"Snapshot record key имеет неверную длину: {file_name}")
    return value


def _record_rows(
    snapshot_id: str, records: dict[str, tuple[dict[str, Any], ...]]
) -> list[RegistrySnapshotRecord]:
    rows: list[RegistrySnapshotRecord] = []
    for file_name in _RECORD_FILES:
        for record in records[file_name]:
            rows.append(
                RegistrySnapshotRecord(
                    snapshot_id=snapshot_id,
                    file_name=file_name,
                    record_key=_record_key(file_name, record),
                    payload_json=_canonical_json(record).decode("utf-8"),
                )
            )
    return rows


def _verify_installed_snapshot(
    header: RegistryIdentitySnapshot,
    records: tuple[RegistrySnapshotRecord, ...],
    resolver_projection: RegistryEventResolverProjection,
) -> VerifiedRegistrySnapshot:
    """Повторно проверить immutable rows и вывести из них event projection."""
    if header.snapshot_kind != "registry_manifest" or header.manifest_json is None:
        raise ValueError("Server snapshot header не содержит полного registry manifest")
    try:
        manifest = json.loads(header.manifest_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Установленный registry manifest повреждён") from exc
    if _canonical_json(manifest).decode("utf-8") != header.manifest_json:
        raise ValueError("Установленный registry manifest неканоничен")
    records_by_file: dict[str, list[dict[str, Any]]] = {name: [] for name in _RECORD_FILES}
    for row in records:
        if row.file_name not in records_by_file:
            raise ValueError("Установленный registry содержит неизвестный файл")
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Установленная registry запись повреждена") from exc
        if (
            not isinstance(payload, dict)
            or _canonical_json(payload).decode("utf-8") != row.payload_json
        ):
            raise ValueError("Установленная registry запись неканонична")
        if _record_key(row.file_name, payload) != row.record_key:
            raise ValueError("Установленный registry record key не соответствует payload")
        records_by_file[row.file_name].append(payload)
    restored: dict[str, tuple[dict[str, Any], ...]] = {}
    for file_name in _RECORD_FILES:
        restored[file_name] = tuple(
            sorted(
                records_by_file[file_name],
                key=lambda item: _record_key(file_name, item),
            )
        )
        encoded = b"".join(_canonical_json(item) + b"\n" for item in restored[file_name])
        expected = manifest.get("files", {}).get(file_name)
        if (
            not isinstance(expected, dict)
            or hashlib.sha256(encoded).hexdigest() != expected.get("sha256")
            or len(encoded) != expected.get("bytes")
            or len(restored[file_name]) != expected.get("count")
        ):
            raise ValueError("Установленные registry records не соответствуют manifest")
    if set(manifest.get("files", {})) != set(_RECORD_FILES):
        raise ValueError("Installed registry manifest имеет неизвестный набор файлов")
    identity_manifest = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    digest = hashlib.sha256(_canonical_json(identity_manifest)).hexdigest()
    if (
        manifest.get("format") != "sports-forecast-entity-registry"
        or manifest.get("registry_schema_version") != EntityRegistry.schema_version
        or manifest.get("snapshot_id") != header.snapshot_id
        or header.snapshot_id != f"ir1:{digest}"
        or header.projection_sha256 != digest
        or manifest.get("format_version") != SNAPSHOT_FORMAT_VERSION
        or header.projection_schema_version != SNAPSHOT_FORMAT_VERSION
        or header.projection_json
        != _canonical_json(
            {
                "snapshot_id": header.snapshot_id,
                "projection_sha256": digest,
                "snapshot_kind": "registry_manifest",
            }
        ).decode("utf-8")
        or header.policy_version != manifest.get("policy_version")
        or header.normalization_version != manifest.get("normalization_version")
    ):
        raise ValueError("Installed registry identity не соответствует manifest")
    meta = ({"registry_schema_version": manifest["registry_schema_version"]},)
    from sports_forecast.identity.snapshot import _build_event_snapshot, _validate_registry_records

    _validate_registry_records({**restored, "_meta": meta})
    event_snapshot = _build_event_snapshot({**restored, "_meta": meta})
    _validate_snapshot(event_snapshot)
    if (
        resolver_projection.snapshot_id != header.snapshot_id
        or resolver_projection.event_snapshot_id != event_snapshot.snapshot_id
        or resolver_projection.projection_sha256 != event_snapshot.projection_sha256
        or resolver_projection.projection_json != event_snapshot.projection_json
    ):
        raise ValueError("Installed event resolver projection не соответствует registry")
    return VerifiedRegistrySnapshot(
        snapshot_id=header.snapshot_id,
        projection_sha256=digest,
        path=Path(),
        manifest=manifest,
        records=restored,
        event_snapshot=event_snapshot,
    )


@dataclass(frozen=True)
class VerifiedPublicationRecord:
    """Publication metadata checked against immutable remote record and pointer."""

    publication_id: str
    sequence: int
    snapshot_id: str
    snapshot_sha256: str
    previous_publication_id: str | None
    published_at: datetime
    actor: str

    @classmethod
    def from_downloaded(cls, downloaded: DownloadedPublication) -> Self:
        """Преобразовать record из проверенного storage download в installer input."""
        record = downloaded.record
        try:
            published_at = datetime.fromisoformat(record.published_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("Downloaded publication содержит неверное время") from exc
        result = cls(
            publication_id=record.publication_id,
            sequence=record.sequence,
            snapshot_id=record.snapshot_id,
            snapshot_sha256=record.snapshot_sha256,
            previous_publication_id=record.previous_publication_id,
            published_at=published_at,
            actor=record.actor,
        )
        result.validate()
        return result

    def validate(self) -> None:
        """Проверить локальные ограничения publication metadata."""
        try:
            valid_uuid = str(UUID(self.publication_id)) == self.publication_id
        except (TypeError, ValueError):
            valid_uuid = False
        if (
            not valid_uuid
            or not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 1
            or self.sequence >= 2**63
            or not isinstance(self.snapshot_sha256, str)
            or not _HEX_SHA256.fullmatch(self.snapshot_sha256)
            or not isinstance(self.snapshot_id, str)
            or self.snapshot_id != f"ir1:{self.snapshot_sha256}"
            or not isinstance(self.published_at, datetime)
            or self.published_at.tzinfo is None
            or self.published_at.utcoffset() is None
            or not isinstance(self.actor, str)
            or not _PROJECT_ACTOR.fullmatch(self.actor)
        ):
            raise ValueError("Publication record содержит некорректные поля")
        if self.previous_publication_id is not None:
            try:
                valid_previous = (
                    str(UUID(self.previous_publication_id)) == self.previous_publication_id
                )
            except (TypeError, ValueError):
                valid_previous = False
            if not valid_previous:
                raise ValueError("Publication previous ID имеет неверный формат")
        if (self.sequence == 1) != (self.previous_publication_id is None):
            raise ValueError("Publication sequence не соответствует previous ID")


@dataclass(frozen=True)
class InstalledEventSnapshot:
    """Event projection, проверенная и закреплённая полным `ir1` snapshot."""

    snapshot_id: str
    event_snapshot: EventIdentitySnapshot

    def resolve(self, ref: CanonicalEventRef) -> EventResolution:
        """Разрешить событие и пометить результат полным закреплённым `ir1`."""
        result = RegistryEventResolver(self.event_snapshot).resolve(ref)
        return replace(result, snapshot_id=self.snapshot_id)

    def resolve_many(self, refs: tuple[CanonicalEventRef, ...]) -> tuple[EventResolution, ...]:
        """Разрешить batch событий с reverse-uniqueness и одним закреплённым `ir1`."""
        results = RegistryEventResolver(self.event_snapshot).resolve_many(refs)
        return tuple(replace(result, snapshot_id=self.snapshot_id) for result in results)


@dataclass(frozen=True)
class InstalledRegistryReader:
    """Resolver полного registry поколения, закреплённого в начале запроса."""

    _snapshot: VerifiedRegistrySnapshot = field(repr=False)
    _entity_reader: RegistrySnapshotReader = field(repr=False, compare=False)
    publication_sequence: int
    publication_id: str

    @property
    def snapshot_id(self) -> str:
        return self._snapshot.snapshot_id

    @property
    def event_snapshot(self) -> InstalledEventSnapshot:
        return InstalledEventSnapshot(self.snapshot_id, self._snapshot.event_snapshot)

    def get_entity(self, entity_id: str) -> Entity:
        """Прочитать проектную сущность из pinned snapshot."""
        return self._entity_reader.get_entity(entity_id)

    def resolve_designation(
        self,
        *,
        source: str,
        kind: EntityKind,
        scope: dict[str, str],
        value_kind: Literal["name", "external_id"],
        raw_value: str,
        at: str | None = None,
    ) -> Resolution:
        """Разрешить внешнее обозначение только по pinned snapshot."""
        return self._entity_reader.resolve_designation(
            source=source,
            kind=kind,
            scope=scope,
            value_kind=value_kind,
            raw_value=raw_value,
            at=at,
        )

    def get_event_mapping(self, canonical_event_id: int, session: Session) -> EventRegistryMapping:
        """Получить bridge и проверить актуальную canonical revision перед runtime use."""
        mapping = session.get(EventRegistryMapping, (self.snapshot_id, canonical_event_id))
        if mapping is None:
            raise KeyError((self.snapshot_id, canonical_event_id))
        if mapping.status == "resolved":
            event = session.get(CanonicalEvent, canonical_event_id)
            if event is None:
                raise KeyError(canonical_event_id)
            scheduled_at = event.scheduled_at
            if scheduled_at is not None and scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
            current = self.event_snapshot.resolve(
                CanonicalEventRef(
                    canonical_event_id=canonical_event_id,
                    sport=event.sport,
                    tournament=event.tournament,
                    source=event.source,
                    source_event_id=event.source_event_id,
                    scheduled_at=scheduled_at,
                    home_participant=event.home_participant,
                    away_participant=event.away_participant,
                )
            )
            project = next(
                (
                    item
                    for item in self._snapshot.event_snapshot.events
                    if item.id == mapping.project_event_id
                ),
                None,
            )
            at = scheduled_at.isoformat() if scheduled_at is not None else None
            tournament = self.resolve_designation(
                source=event.source,
                kind="tournament",
                scope={"sport": event.sport},
                value_kind="name",
                raw_value=event.tournament,
                at=at,
            )
            scope = {
                "sport": event.sport,
                "tournament": tournament.entity_id or "",
            }
            home = self.resolve_designation(
                source=event.source,
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=event.home_participant or "",
                at=at,
            )
            away = self.resolve_designation(
                source=event.source,
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=event.away_participant or "",
                at=at,
            )
            if (
                current.status != "resolved"
                or current.project_event_id != mapping.project_event_id
                or project is None
                or project.sport != event.sport
                or tournament.status != "resolved"
                or tournament.entity_id != project.tournament_id
                or home.status != "resolved"
                or home.entity_id != project.home_team_id
                or away.status != "resolved"
                or away.entity_id != project.away_team_id
            ):
                return EventRegistryMapping(
                    snapshot_id=self.snapshot_id,
                    canonical_event_id=canonical_event_id,
                    project_event_id=None,
                    status="conflict",
                    reason="Текущая canonical revision противоречит закреплённому bridge",
                    policy_version=mapping.policy_version,
                )
        return cast(EventRegistryMapping, mapping)


def load_installed_event_snapshot(session: Session, *, snapshot_id: str) -> InstalledEventSnapshot:
    """Проверить full `ir1` projection в БД и вернуть его закреплённый event resolver."""
    loaded = _load_snapshot_rows(session, snapshot_id)
    return InstalledEventSnapshot(snapshot_id, loaded.event_snapshot)


def _cache_footprint(
    header: RegistryIdentitySnapshot,
    records: tuple[RegistrySnapshotRecord, ...],
    resolver_projection: RegistryEventResolverProjection,
) -> int:
    """Оценить память с запасом на Python объекты, а не только UTF-8 payload."""
    return (
        (len(header.manifest_json.encode("utf-8")) if header.manifest_json else 0)
        + len(resolver_projection.projection_json.encode("utf-8"))
        + sum(len(row.payload_json.encode("utf-8")) + 512 for row in records)
    )


def _clear_uncommitted_snapshot_cache_marker(session: Session, transaction: Any) -> None:
    if transaction.parent is None:
        session.info.pop(_UNCOMMITTED_SNAPSHOT_IDS, None)


event.listen(Session, "after_transaction_end", _clear_uncommitted_snapshot_cache_marker)


def _mark_snapshot_uncommitted(session: Session, snapshot_id: str) -> None:
    pending_ids = session.info.setdefault(_UNCOMMITTED_SNAPSHOT_IDS, set())
    pending_ids.add(snapshot_id)


def _cache_engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def _cache_verified_snapshot(
    key: tuple[Engine, str], snapshot: VerifiedRegistrySnapshot, footprint: int
) -> None:
    """Сохранить только небольшой проверенный immutable snapshot в bounded LRU."""
    global _SNAPSHOT_CACHE_BYTES  # noqa: PLW0603
    if footprint > _SNAPSHOT_CACHE_MAX_BYTES:
        return
    with _SNAPSHOT_CACHE_LOCK:
        prior = _SNAPSHOT_CACHE.pop(key, None)
        if prior is not None:
            _SNAPSHOT_CACHE_BYTES -= prior.footprint
        while _SNAPSHOT_CACHE and (
            _SNAPSHOT_CACHE_BYTES + footprint > _SNAPSHOT_CACHE_MAX_BYTES
            or len(_SNAPSHOT_CACHE) >= _SNAPSHOT_CACHE_MAX_ENTRIES
        ):
            _, evicted = _SNAPSHOT_CACHE.popitem(last=False)
            _SNAPSHOT_CACHE_BYTES -= evicted.footprint
        _SNAPSHOT_CACHE[key] = _SnapshotCacheEntry(
            snapshot,
            RegistrySnapshotReader(snapshot),
            footprint,
        )
        _SNAPSHOT_CACHE_BYTES += footprint


def _load_snapshot_rows(
    session: Session, snapshot_id: str, *, use_cache: bool = True
) -> VerifiedRegistrySnapshot:
    cache_key = (_cache_engine(session), snapshot_id)
    pending_ids = session.info.get(_UNCOMMITTED_SNAPSHOT_IDS, set())
    use_cache = use_cache and snapshot_id not in pending_ids
    if use_cache:
        with _SNAPSHOT_CACHE_LOCK:
            cached = _SNAPSHOT_CACHE.get(cache_key)
            if cached is not None:
                _SNAPSHOT_CACHE.move_to_end(cache_key)
                return cached.snapshot
    header = session.get(RegistryIdentitySnapshot, snapshot_id)
    if header is None:
        raise KeyError(snapshot_id)
    records = tuple(
        session.scalars(
            select(RegistrySnapshotRecord)
            .where(RegistrySnapshotRecord.__table__.c.snapshot_id == snapshot_id)
            .order_by(
                RegistrySnapshotRecord.__table__.c.file_name,
                RegistrySnapshotRecord.__table__.c.record_key,
            )
        ).all()
    )
    resolver_projection = session.get(RegistryEventResolverProjection, snapshot_id)
    if resolver_projection is None:
        raise ValueError("Installed registry не содержит event resolver projection")
    verified = _verify_installed_snapshot(header, records, resolver_projection)
    if use_cache:
        _cache_verified_snapshot(
            cache_key,
            verified,
            _cache_footprint(header, records, resolver_projection),
        )
    return verified


def pin_installed_registry(session: Session) -> InstalledRegistryReader:
    """Сначала закрепить active ir1, затем читать только immutable rows этой версии."""
    active = session.get(ActiveRegistryInstallation, 1)
    if active is None:
        raise RuntimeError("Registry installation ещё не доступна")
    snapshot_id = active.snapshot_id
    sequence = active.publication_sequence
    publication_id = active.publication_id
    publication = session.get(RegistryPublication, sequence)
    if (
        publication is None
        or publication.publication_id != publication_id
        or publication.snapshot_id != snapshot_id
    ):
        raise ValueError("Active pointer не соответствует immutable publication record")
    snapshot = _load_snapshot_rows(session, snapshot_id)
    return _make_reader(session, snapshot, sequence, publication_id, use_cache=True)


def refresh_active_event_bridge(session: Session) -> tuple[EventRegistryMapping, ...]:
    """Добавить mappings новых canonical rows к текущему ir1 без правки старых."""
    lock = session.scalar(
        select(RegistryInstallationLock)
        .where(RegistryInstallationLock.__table__.c.id == 1)
        .with_for_update()
    )
    if lock is None:
        raise RuntimeError("Registry installation lock отсутствует")
    active = session.get(ActiveRegistryInstallation, 1)
    if active is None:
        raise RuntimeError("Registry installation ещё не доступна")
    snapshot = _load_snapshot_rows(session, active.snapshot_id)
    before = {
        item.canonical_event_id
        for item in session.scalars(
            select(EventRegistryMapping).where(
                EventRegistryMapping.__table__.c.snapshot_id == active.snapshot_id
            )
        )
    }
    _install_event_bridge(session, snapshot)
    return tuple(
        item
        for item in session.scalars(
            select(EventRegistryMapping).where(
                EventRegistryMapping.__table__.c.snapshot_id == active.snapshot_id
            )
        )
        if item.canonical_event_id not in before
    )


def _make_reader(
    session: Session,
    snapshot: VerifiedRegistrySnapshot,
    sequence: int,
    publication_id: str,
    *,
    use_cache: bool,
) -> InstalledRegistryReader:
    entity_reader: RegistrySnapshotReader | None = None
    if use_cache:
        key = (_cache_engine(session), snapshot.snapshot_id)
        with _SNAPSHOT_CACHE_LOCK:
            entry = _SNAPSHOT_CACHE.get(key)
            if entry is not None:
                _SNAPSHOT_CACHE.move_to_end(key)
                entity_reader = entry.entity_reader
    if entity_reader is None:
        entity_reader = RegistrySnapshotReader(snapshot)
    return InstalledRegistryReader(snapshot, entity_reader, sequence, publication_id)


def install_registry_publication(
    session: Session,
    snapshot_path: Path,
    *,
    publication: VerifiedPublicationRecord,
) -> InstalledRegistryReader:
    """Установить проверенный snapshot и атомарно активировать publication."""
    publication.validate()
    verified = verify_registry_snapshot(Path(snapshot_path))
    if (
        publication.snapshot_id != verified.snapshot_id
        or publication.snapshot_sha256 != verified.projection_sha256
    ):
        raise ValueError("Publication record не соответствует проверенному snapshot")
    publication_sequence = publication.sequence
    publication_id = publication.publication_id
    lock_table = RegistryInstallationLock.__table__
    session.execute(
        update(RegistryInstallationLock)
        .where(lock_table.c.id == 1)
        .values(lock_version=lock_table.c.lock_version)
    )
    session.execute(
        select(RegistryInstallationLock).where(lock_table.c.id == 1).with_for_update()
    ).scalar_one()
    active = session.execute(
        select(ActiveRegistryInstallation)
        .where(ActiveRegistryInstallation.__table__.c.id == 1)
        .with_for_update()
    ).scalar_one_or_none()
    existing = session.get(RegistryPublication, publication_sequence)
    if existing is not None:
        if (
            existing.publication_id != publication_id
            or existing.snapshot_id != verified.snapshot_id
            or existing.previous_publication_id != publication.previous_publication_id
            or existing.actor != publication.actor
            or existing.published_at
            != publication.published_at.astimezone(UTC).replace(tzinfo=None)
        ):
            raise ValueError("Publication sequence уже закреплён за другим содержимым")
        if active is None or active.publication_sequence < publication_sequence:
            raise ValueError("Историческую publication нельзя активировать повторным импортом")
        if (
            active.publication_sequence == publication_sequence
            and active.publication_id != publication_id
        ):
            raise ValueError("Active publication sequence имеет другой ID")
        return _reader_for_publication(
            session, publication_sequence, publication_id, verified.snapshot_id
        )
    if (
        session.scalar(
            select(RegistryPublication.__table__.c.publication_sequence).where(
                RegistryPublication.__table__.c.publication_id == publication_id
            )
        )
        is not None
    ):
        raise ValueError("Publication ID уже закреплён за другим sequence")
    expected_sequence = active.publication_sequence + 1 if active is not None else 1
    expected_previous_id = active.publication_id if active is not None else None
    if (
        publication_sequence != expected_sequence
        or publication.previous_publication_id != expected_previous_id
    ):
        raise ValueError("Publication sequence/previous ID не продолжают установленную цепочку")

    with session.begin_nested():
        _install_immutable_projection(session, verified)
        # Прочитать все rows из staging transaction до изменения active pointer.
        installed = _load_snapshot_rows(session, verified.snapshot_id, use_cache=False)
        if installed.snapshot_id != verified.snapshot_id:
            raise ValueError("Server staging projection не прошла проверку")
        session.add(
            RegistryPublication(
                publication_sequence=publication_sequence,
                publication_id=publication_id,
                snapshot_id=verified.snapshot_id,
                previous_publication_id=publication.previous_publication_id,
                published_at=publication.published_at.astimezone(UTC).replace(tzinfo=None),
                actor=publication.actor,
            )
        )
        session.flush()
        if active is None:
            active = ActiveRegistryInstallation(
                id=1,
                publication_sequence=publication_sequence,
                publication_id=publication_id,
                snapshot_id=verified.snapshot_id,
            )
            session.add(active)
        else:
            active.publication_sequence = publication_sequence
            active.publication_id = publication_id
            active.snapshot_id = verified.snapshot_id
        session.flush()
    _mark_snapshot_uncommitted(session, verified.snapshot_id)
    return _make_reader(
        session,
        installed,
        publication_sequence,
        publication_id,
        use_cache=False,
    )


def _install_immutable_projection(session: Session, verified: VerifiedRegistrySnapshot) -> None:
    header = session.get(RegistryIdentitySnapshot, verified.snapshot_id)
    if header is None:
        header = RegistryIdentitySnapshot(
            snapshot_id=verified.snapshot_id,
            snapshot_kind="registry_manifest",
            projection_sha256=verified.projection_sha256,
            projection_schema_version=int(verified.manifest["format_version"]),
            policy_version=str(verified.manifest["policy_version"]),
            normalization_version=str(verified.manifest["normalization_version"]),
            projection_json=_canonical_json(
                {
                    "snapshot_id": verified.snapshot_id,
                    "projection_sha256": verified.projection_sha256,
                    "snapshot_kind": "registry_manifest",
                }
            ).decode("utf-8"),
            manifest_json=_canonical_json(verified.manifest).decode("utf-8"),
        )
        session.add(header)
        session.flush()
        session.add_all(_record_rows(verified.snapshot_id, verified.records))
        projection = verified.event_snapshot
        session.add(
            RegistryEventResolverProjection(
                snapshot_id=verified.snapshot_id,
                event_snapshot_id=projection.snapshot_id,
                projection_sha256=projection.projection_sha256,
                projection_json=projection.projection_json,
            )
        )
        session.flush()
    else:
        existing = _load_snapshot_rows(session, verified.snapshot_id, use_cache=False)
        if existing.projection_sha256 != verified.projection_sha256:
            raise ValueError("Snapshot ID уже установлен с другим содержимым")
    _install_event_bridge(session, verified)


def _install_event_bridge(session: Session, verified: VerifiedRegistrySnapshot) -> None:
    rows = session.scalars(select(CanonicalEvent).order_by(CanonicalEvent.__table__.c.id)).all()
    existing_rows = session.scalars(
        select(EventRegistryMapping).where(
            EventRegistryMapping.__table__.c.snapshot_id == verified.snapshot_id
        )
    ).all()
    existing_by_event_id = {item.canonical_event_id: item for item in existing_rows}
    refs_by_event_id = {
        row.id: CanonicalEventRef(
            canonical_event_id=row.id,
            sport=row.sport,
            tournament=row.tournament,
            source=row.source,
            source_event_id=row.source_event_id,
            scheduled_at=(
                row.scheduled_at.replace(tzinfo=UTC)
                if row.scheduled_at.tzinfo is None
                else row.scheduled_at
            ),
            home_participant=row.home_participant,
            away_participant=row.away_participant,
        )
        for row in rows
    }
    new_rows = tuple(row for row in rows if row.id not in existing_by_event_id)
    new_refs = tuple(refs_by_event_id[row.id] for row in new_rows)
    resolver = RegistryEventResolver(verified.event_snapshot)
    pinned_claims: list[tuple[str, str, str, str, str]] = []
    for mapping in existing_rows:
        if mapping.status != "resolved" or mapping.project_event_id is None:
            continue
        ref = refs_by_event_id.get(mapping.canonical_event_id)
        if ref is None:
            continue
        tournament_status, tournament_id = resolver._resolve_alias(
            ref.source,
            "tournament",
            {"sport": ref.sport},
            ref.tournament,
            at=_parse_utc(ref.scheduled_at),
        )
        if tournament_status == "resolved" and tournament_id is not None:
            pinned_claims.append(
                (
                    ref.source,
                    ref.sport,
                    tournament_id,
                    mapping.project_event_id,
                    ref.source_event_id,
                )
            )
    results = resolver.resolve_many(new_refs, pinned_claims=tuple(pinned_claims))
    for canonical, result in zip(new_rows, results, strict=True):
        session.add(
            EventRegistryMapping(
                snapshot_id=verified.snapshot_id,
                canonical_event_id=canonical.id,
                project_event_id=result.project_event_id,
                status=result.status,
                reason=result.reason,
                policy_version=result.policy_version,
            )
        )
    session.flush()


def _reader_for_publication(
    session: Session, sequence: int, publication_id: str, snapshot_id: str
) -> InstalledRegistryReader:
    snapshot = _load_snapshot_rows(session, snapshot_id, use_cache=False)
    return _make_reader(session, snapshot, sequence, publication_id, use_cache=False)
