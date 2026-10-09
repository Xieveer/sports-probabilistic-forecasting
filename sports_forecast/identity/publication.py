"""Публикация проверенных registry snapshots с CAS указателя current."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from sports_forecast.identity.snapshot import SnapshotLimits, verify_registry_snapshot


_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SNAPSHOT_FILES = (
    "manifest.json",
    "entities.jsonl",
    "designations.jsonl",
    "decisions.jsonl",
    "events.jsonl",
    "memberships.jsonl",
)


class PublicationError(RuntimeError):
    """Публикация registry не завершена."""


class ConditionalWriteConflictError(PublicationError):
    """CAS condition не совпало с текущим Object Storage объектом."""


class UnsupportedConditionalWriteError(PublicationError):
    """Object Storage не поддерживает требуемую условную запись."""


class PublicationOutcomeUnknownError(PublicationError):
    """Ответ PUT current потерян, а его результат нельзя установить."""


class Storage(Protocol):
    """Минимальный транспорт с чтением и условным PUT, без Delete/List."""

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject: ...

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str: ...


@dataclass(frozen=True)
class StorageObject:
    """Объект и ETag, используемый только как CAS token."""

    body: bytes
    etag: str


@dataclass(frozen=True)
class PublicationRecord:
    """Immutable audit record о публикации одного snapshot."""

    publication_id: str
    sequence: int
    snapshot_id: str
    snapshot_sha256: str
    previous_publication_id: str | None
    published_at: str
    actor: str


@dataclass(frozen=True)
class _Current:
    publication_id: str
    sequence: int
    snapshot_id: str
    snapshot_sha256: str
    previous_publication_id: str | None
    body: bytes
    etag: str


@dataclass(frozen=True)
class DownloadedPublication:
    """Опубликованная запись и проверенный локальный snapshot package."""

    record: PublicationRecord
    snapshot_path: Path


@dataclass(frozen=True)
class _PendingPublication:
    record: PublicationRecord
    pointer_body: bytes
    base_etag: str | None
    base_body_sha256: str | None
    base_publication_id: str | None
    base_sequence: int


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _object_key(prefix: str, *parts: str) -> str:
    return "/".join((prefix, *parts))


def _record_fields(record: PublicationRecord) -> dict[str, object]:
    return {
        "publication_id": record.publication_id,
        "sequence": record.sequence,
        "snapshot_id": record.snapshot_id,
        "snapshot_sha256": record.snapshot_sha256,
        "previous_publication_id": record.previous_publication_id,
        "published_at": record.published_at,
        "actor": record.actor,
    }


def _pointer_body(record: PublicationRecord) -> bytes:
    fields = _record_fields(record)
    return _canonical_json(
        {
            key: fields[key]
            for key in (
                "publication_id",
                "sequence",
                "snapshot_id",
                "snapshot_sha256",
                "previous_publication_id",
            )
        }
    )


def _validate_remote_manifest(
    body: bytes, record: PublicationRecord, max_bytes: int
) -> dict[str, Any]:
    try:
        manifest = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("Remote snapshot manifest повреждён") from exc
    if not isinstance(manifest, dict) or body != _canonical_json(manifest):
        raise PublicationError("Remote snapshot manifest неканоничен")
    if manifest.get("snapshot_id") != record.snapshot_id:
        raise PublicationError("Remote manifest ID не совпадает с publication record")
    identity = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    digest = hashlib.sha256(_canonical_json(identity).removesuffix(b"\n")).hexdigest()
    files = manifest.get("files")
    expected_files = set(_SNAPSHOT_FILES) - {"manifest.json"}
    if (
        digest != record.snapshot_sha256
        or not isinstance(files, dict)
        or set(files) != expected_files
    ):
        raise PublicationError("Remote manifest hash или список файлов неверен")
    limits = SnapshotLimits()
    declared_bytes = len(body)
    for filename in expected_files:
        descriptor = files[filename]
        if not isinstance(descriptor, dict):
            raise PublicationError("Remote manifest содержит неверный file descriptor")
        file_bytes = descriptor.get("bytes")
        count = descriptor.get("count")
        file_digest = descriptor.get("sha256")
        if (
            not isinstance(file_bytes, int)
            or isinstance(file_bytes, bool)
            or not 0 <= file_bytes <= limits.max_file_bytes
            or not isinstance(count, int)
            or isinstance(count, bool)
            or not 0 <= count <= limits.max_records_per_file
            or not isinstance(file_digest, str)
            or not _HEX_SHA256.fullmatch(file_digest)
        ):
            raise PublicationError("Remote manifest содержит неверные file limits/checksum")
        declared_bytes += file_bytes
        if declared_bytes > min(max_bytes, limits.max_total_bytes):
            raise PublicationError("Snapshot превышает заданный download byte limit")
    if declared_bytes > min(max_bytes, limits.max_total_bytes):
        raise PublicationError("Snapshot превышает заданный download byte limit")
    return manifest


def _parse_current(raw: StorageObject) -> _Current:
    try:
        value = json.loads(raw.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("Удалённый current.json повреждён") from exc
    if not isinstance(value, dict) or set(value) != {
        "publication_id",
        "sequence",
        "snapshot_id",
        "snapshot_sha256",
        "previous_publication_id",
    }:
        raise PublicationError("Удалённый current.json имеет неверную форму")
    try:
        pointer = _Current(
            publication_id=str(value["publication_id"]),
            sequence=value["sequence"],
            snapshot_id=str(value["snapshot_id"]),
            snapshot_sha256=str(value["snapshot_sha256"]),
            previous_publication_id=value["previous_publication_id"],
            body=raw.body,
            etag=raw.etag,
        )
    except (KeyError, TypeError) as exc:
        raise PublicationError("Удалённый current.json не содержит поля протокола") from exc
    if (
        not isinstance(pointer.sequence, int)
        or isinstance(pointer.sequence, bool)
        or pointer.sequence < 1
        or pointer.sequence >= 2**63
        or not _HEX_SHA256.fullmatch(pointer.snapshot_sha256)
        or pointer.snapshot_id != f"ir1:{pointer.snapshot_sha256}"
        or not _is_uuid(pointer.publication_id)
        or (
            pointer.previous_publication_id is not None
            and not _is_uuid(pointer.previous_publication_id)
        )
        or raw.body != _canonical_json(value)
        or not raw.etag
    ):
        raise PublicationError("Удалённый current.json содержит недопустимые значения")
    if (pointer.sequence == 1) != (pointer.previous_publication_id is None):
        raise PublicationError("current.json нарушает связность publication sequence")
    return pointer


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _safe_prefix(prefix: str) -> str:
    normalized = prefix.strip("/")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Некорректный Object Storage prefix")
    return normalized


def read_publication_by_id(
    storage: Storage, *, prefix: str, publication_id: str
) -> PublicationRecord:
    """Прочитать и проверить immutable publication record по UUID."""
    normalized_prefix = _safe_prefix(prefix)
    if not _is_uuid(publication_id):
        raise ValueError("Некорректный publication ID")
    key = _object_key(normalized_prefix, "publications", f"{publication_id}.json")
    remote = storage.get(key)
    try:
        value = json.loads(remote.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("Publication record повреждён") from exc
    fields = {
        "publication_id",
        "sequence",
        "snapshot_id",
        "snapshot_sha256",
        "previous_publication_id",
        "published_at",
        "actor",
    }
    if not isinstance(value, dict) or set(value) != fields or remote.body != _canonical_json(value):
        raise PublicationError("Publication record не соответствует схеме")
    try:
        record = PublicationRecord(
            publication_id=value["publication_id"],
            sequence=value["sequence"],
            snapshot_id=value["snapshot_id"],
            snapshot_sha256=value["snapshot_sha256"],
            previous_publication_id=value["previous_publication_id"],
            published_at=value["published_at"],
            actor=value["actor"],
        )
    except (KeyError, TypeError) as exc:
        raise PublicationError("Publication record содержит неверные значения") from exc
    if (
        not _is_uuid(record.publication_id)
        or record.publication_id != publication_id
        or not isinstance(record.sequence, int)
        or isinstance(record.sequence, bool)
        or record.sequence < 1
        or record.sequence >= 2**63
        or not _HEX_SHA256.fullmatch(record.snapshot_sha256)
        or record.snapshot_id != f"ir1:{record.snapshot_sha256}"
        or (record.sequence == 1) != (record.previous_publication_id is None)
        or (
            record.previous_publication_id is not None
            and not _is_uuid(record.previous_publication_id)
        )
        or not isinstance(record.published_at, str)
        or not isinstance(record.actor, str)
        or not _ACTOR.fullmatch(record.actor)
    ):
        raise PublicationError("Publication record содержит недопустимые значения")
    try:
        timestamp = datetime.fromisoformat(record.published_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError("Publication record содержит неверное время") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise PublicationError("Publication record timestamp должен включать timezone")
    return record


def read_current_publication(storage: Storage, *, prefix: str) -> PublicationRecord:
    """Один раз прочитать current pointer и проверить указанную immutable запись."""
    normalized_prefix = _safe_prefix(prefix)
    current = _parse_current(storage.get(_object_key(normalized_prefix, "current.json")))
    return _publication_for_pointer(storage, normalized_prefix, current)


def _publication_for_pointer(storage: Storage, prefix: str, pointer: _Current) -> PublicationRecord:
    try:
        record = read_publication_by_id(
            storage, prefix=prefix, publication_id=pointer.publication_id
        )
    except FileNotFoundError as exc:
        raise PublicationError(
            "current.json ссылается на отсутствующий publication record"
        ) from exc
    if (
        record.sequence != pointer.sequence
        or record.snapshot_id != pointer.snapshot_id
        or record.snapshot_sha256 != pointer.snapshot_sha256
        or record.previous_publication_id != pointer.previous_publication_id
    ):
        raise PublicationError("current.json не соответствует immutable publication record")
    return record


def download_publication_snapshot(
    storage: Storage,
    *,
    prefix: str,
    publication_id: str,
    destination: Path,
    max_bytes: int = 1024 * 1024 * 1024,
) -> Path:
    """Скачать по ID публикации и атомарно сохранить полностью проверенный package."""
    if max_bytes < 1:
        raise ValueError("max_bytes должен быть положительным")
    normalized_prefix = _safe_prefix(prefix)
    record = read_publication_by_id(
        storage, prefix=normalized_prefix, publication_id=publication_id
    )
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise PublicationError("Download root не должен быть symlink")
    package = root / record.snapshot_sha256
    if package.is_symlink():
        raise PublicationError("Локальный package path не должен быть symlink")
    if package.exists():
        try:
            cached_bytes = sum((package / filename).stat().st_size for filename in _SNAPSHOT_FILES)
        except OSError as exc:
            raise PublicationError("Локальный cached package неполон") from exc
        if cached_bytes > max_bytes:
            raise PublicationError("Cached snapshot превышает заданный download byte limit")
        verified = verify_registry_snapshot(package)
        if verified.snapshot_id != record.snapshot_id:
            raise PublicationError("Локальный package не совпадает с publication snapshot")
        return package
    temporary = Path(tempfile.mkdtemp(prefix=".registry-download-", dir=root))
    try:
        manifest_key = _object_key(
            normalized_prefix, "snapshots", record.snapshot_sha256, "manifest.json"
        )
        manifest_limit = min(max_bytes, SnapshotLimits().max_line_bytes * 4)
        manifest_body = storage.get(manifest_key, max_bytes=manifest_limit).body
        manifest = _validate_remote_manifest(manifest_body, record, max_bytes)
        (temporary / "manifest.json").write_bytes(manifest_body)
        downloaded_bytes = len(manifest_body)
        for filename in _SNAPSHOT_FILES:
            if filename == "manifest.json":
                continue
            key = _object_key(normalized_prefix, "snapshots", record.snapshot_sha256, filename)
            descriptor = manifest["files"][filename]
            remaining = max_bytes - downloaded_bytes
            body = storage.get(key, max_bytes=remaining).body
            if (
                len(body) != descriptor["bytes"]
                or hashlib.sha256(body).hexdigest() != descriptor["sha256"]
            ):
                raise PublicationError("Remote snapshot file не совпадает с manifest")
            downloaded_bytes += len(body)
            (temporary / filename).write_bytes(body)
        verified = verify_registry_snapshot(temporary)
        if verified.snapshot_id != record.snapshot_id:
            raise PublicationError("Downloaded package не совпадает с publication record")
        try:
            temporary.rename(package)
        except OSError as exc:
            if not package.is_dir() or package.is_symlink():
                raise
            existing = verify_registry_snapshot(package)
            if existing.snapshot_id != record.snapshot_id:
                raise PublicationError(
                    "Конкурентная загрузка создала другой local package"
                ) from exc
        return package
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def download_current_publication(
    storage: Storage,
    *,
    prefix: str,
    destination: Path,
    max_bytes: int = 1024 * 1024 * 1024,
) -> DownloadedPublication:
    """Закрепить текущую publication запись и скачать snapshot ровно этой версии."""
    record = read_current_publication(storage, prefix=prefix)
    path = download_publication_snapshot(
        storage,
        prefix=prefix,
        publication_id=record.publication_id,
        destination=destination,
        max_bytes=max_bytes,
    )
    return DownloadedPublication(record=record, snapshot_path=path)


class RegistryPublisher:
    """Выгрузить immutable package и затем условно переключить current pointer."""

    def __init__(
        self,
        storage: Storage,
        *,
        prefix: str,
        lock_path: Path,
        actor: str,
    ) -> None:
        self._storage = storage
        self._prefix = _safe_prefix(prefix)
        self._lock_path = Path(lock_path)
        self._pending_path = self._lock_path.with_name(f"{self._lock_path.name}.pending.json")
        if not _ACTOR.fullmatch(actor):
            raise ValueError(
                "Actor должен соответствовать ASCII идентификатору длиной 1–64 символа"
            )
        self._actor = actor

    def publish(self, snapshot_path: Path) -> PublicationRecord:
        """Опубликовать snapshot; передача прежней версии создаёт новый rollback sequence."""
        snapshot = verify_registry_snapshot(Path(snapshot_path))
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                pending = self._resume_pending_locked()
                if pending is not None and pending.snapshot_id == snapshot.snapshot_id:
                    return pending
                return self._publish_locked(snapshot.path, snapshot.snapshot_id, snapshot.manifest)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @property
    def pending_intent_path(self) -> Path:
        """Путь к durable intent, требующему восстановления после неизвестного результата."""
        return self._pending_path

    def resume_pending(self) -> PublicationRecord | None:
        """Возобновить сохранённую публикацию, не создавая новый publication ID."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                return self._resume_pending_locked()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _resume_pending_locked(self) -> PublicationRecord | None:
        if not self._pending_path.exists():
            return None
        pending = self._read_pending()
        current_key = _object_key(self._prefix, "current.json")
        try:
            current = self._read_current(current_key)
        except FileNotFoundError:
            current = None
        if current is not None and current.body == pending.pointer_body:
            self._verify_remote_publication_record(pending.record)
            self._verify_remote_snapshot(pending.record)
            self._verify_remote_publication_record(pending.record)
            self._clear_pending()
            return pending.record

        if not self._matches_pending_base(current, pending):
            raise ConditionalWriteConflictError(
                f"Object Storage current изменился; intent {pending.record.publication_id} сохранён в "
                f"{self._pending_path} и требует ручного разрешения"
            )
        self._verify_remote_publication_record(pending.record)
        self._verify_remote_snapshot(pending.record)
        try:
            self._storage.put(
                current_key,
                pending.pointer_body,
                if_match=pending.base_etag,
                if_none_match=pending.base_etag is None,
            )
        except ConditionalWriteConflictError as conflict:
            try:
                observed = self._read_current(current_key)
            except Exception as exc:
                raise ConditionalWriteConflictError(
                    f"CAS conflict; intent {pending.record.publication_id} сохранён в {self._pending_path}"
                ) from exc
            if observed.body == pending.pointer_body:
                self._verify_remote_publication_record(pending.record)
                self._verify_remote_snapshot(pending.record)
                self._verify_remote_publication_record(pending.record)
                self._clear_pending()
                return pending.record
            raise ConditionalWriteConflictError(
                f"CAS conflict; intent {pending.record.publication_id} сохранён в {self._pending_path}"
            ) from conflict
        except UnsupportedConditionalWriteError:
            raise
        except Exception as exc:
            try:
                observed = self._read_current(current_key)
            except Exception as read_error:
                raise PublicationOutcomeUnknownError(
                    f"Результат повтора неизвестен; intent сохранён в {self._pending_path}"
                ) from read_error
            if observed.body != pending.pointer_body:
                if not self._matches_pending_base(observed, pending):
                    raise ConditionalWriteConflictError(
                        f"current изменился; intent {pending.record.publication_id} сохранён в "
                        f"{self._pending_path}"
                    ) from exc
                raise PublicationOutcomeUnknownError(
                    f"PUT не подтверждён; intent сохранён в {self._pending_path}"
                ) from exc
        self._verify_remote_publication_record(pending.record)
        self._clear_pending()
        return pending.record

    @staticmethod
    def _matches_pending_base(current: _Current | None, pending: _PendingPublication) -> bool:
        if pending.base_etag is None:
            return current is None
        return (
            current is not None
            and current.etag == pending.base_etag
            and hashlib.sha256(current.body).hexdigest() == pending.base_body_sha256
            and current.publication_id == pending.base_publication_id
            and current.sequence == pending.base_sequence
        )

    def _read_pending(self) -> _PendingPublication:
        try:
            payload = self._pending_path.read_bytes()
            value = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicationError(
                "Локальный publication intent повреждён; остановлена публикация"
            ) from exc
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "format",
                "record",
                "base_etag",
                "base_body_sha256",
                "base_publication_id",
                "base_sequence",
            }
            or value.get("format") != "registry-publication-intent-v1"
            or payload != _canonical_json(value)
            or not isinstance(value.get("record"), dict)
        ):
            raise PublicationError("Локальный publication intent не соответствует схеме")
        raw_record = value["record"]
        if set(raw_record) != {
            "publication_id",
            "sequence",
            "snapshot_id",
            "snapshot_sha256",
            "previous_publication_id",
            "published_at",
            "actor",
        }:
            raise PublicationError("Локальный publication intent содержит неверную запись")
        record = PublicationRecord(**raw_record)
        if (
            not _is_uuid(record.publication_id)
            or not isinstance(record.sequence, int)
            or isinstance(record.sequence, bool)
            or record.sequence < 1
            or record.sequence >= 2**63
            or not isinstance(record.snapshot_sha256, str)
            or not _HEX_SHA256.fullmatch(record.snapshot_sha256)
            or not isinstance(record.snapshot_id, str)
            or record.snapshot_id != f"ir1:{record.snapshot_sha256}"
            or not isinstance(record.actor, str)
            or not _ACTOR.fullmatch(record.actor)
            or (record.sequence == 1) != (record.previous_publication_id is None)
            or (
                record.previous_publication_id is not None
                and not _is_uuid(record.previous_publication_id)
            )
        ):
            raise PublicationError("Локальный publication intent содержит неверные ID/record")
        try:
            timestamp = datetime.fromisoformat(record.published_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise PublicationError("Локальный publication intent содержит неверное время") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise PublicationError(
                "Локальный publication intent timestamp должен включать timezone"
            )
        pointer_body = _pointer_body(record)
        base_etag = value.get("base_etag")
        base_hash = value.get("base_body_sha256")
        base_publication_id = value.get("base_publication_id")
        base_sequence = value.get("base_sequence")
        if (
            (base_etag is None) != (base_hash is None)
            or (base_etag is not None and (not isinstance(base_etag, str) or not base_etag))
            or (
                base_hash is not None
                and (not isinstance(base_hash, str) or not _HEX_SHA256.fullmatch(base_hash))
            )
        ):
            raise PublicationError("Локальный publication intent содержит неверный CAS baseline")
        if base_etag is None:
            valid_base = (
                base_publication_id is None
                and isinstance(base_sequence, int)
                and not isinstance(base_sequence, bool)
                and base_sequence == 0
            )
        else:
            valid_base = (
                _is_uuid(base_publication_id)
                and isinstance(base_sequence, int)
                and not isinstance(base_sequence, bool)
                and base_sequence >= 1
                and record.previous_publication_id == base_publication_id
                and record.sequence == base_sequence + 1
            )
        if not valid_base or (record.sequence == 1) != (record.previous_publication_id is None):
            raise PublicationError("Локальный publication intent нарушает sequence chain")
        if not isinstance(base_sequence, int) or isinstance(base_sequence, bool):
            raise PublicationError("Локальный publication intent содержит неверную sequence")
        return _PendingPublication(
            record,
            pointer_body,
            base_etag,
            base_hash,
            base_publication_id,
            base_sequence,
        )

    def _write_pending(self, record: PublicationRecord, previous: _Current | None) -> None:
        self._pending_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json(
            {
                "format": "registry-publication-intent-v1",
                "record": _record_fields(record),
                "base_etag": previous.etag if previous else None,
                "base_body_sha256": (
                    hashlib.sha256(previous.body).hexdigest() if previous else None
                ),
                "base_publication_id": previous.publication_id if previous else None,
                "base_sequence": previous.sequence if previous else 0,
            }
        )
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self._pending_path.name}.", dir=self._pending_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self._pending_path)
            directory_fd = os.open(self._pending_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _clear_pending(self) -> None:
        self._pending_path.unlink(missing_ok=True)
        directory_fd = os.open(self._pending_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _verify_remote_snapshot(self, record: PublicationRecord) -> None:
        temporary = Path(
            tempfile.mkdtemp(prefix=".registry-intent-verify-", dir=self._pending_path.parent)
        )
        try:
            for filename in _SNAPSHOT_FILES:
                key = _object_key(self._prefix, "snapshots", record.snapshot_sha256, filename)
                (temporary / filename).write_bytes(self._storage.get(key).body)
            verified = verify_registry_snapshot(temporary)
            if verified.snapshot_id != record.snapshot_id:
                raise PublicationError("Remote package не совпадает с pending publication intent")
        finally:
            shutil.rmtree(temporary)

    def _verify_remote_publication_record(self, expected: PublicationRecord) -> None:
        key = _object_key(self._prefix, "publications", f"{expected.publication_id}.json")
        remote = self._storage.get(key)
        if remote.body != _canonical_json(_record_fields(expected)):
            raise PublicationError("Remote publication record не совпадает с pending intent")
        actual = read_publication_by_id(
            self._storage, prefix=self._prefix, publication_id=expected.publication_id
        )
        if actual != expected:
            raise PublicationError("Remote publication record не совпадает с pending intent")

    def _publish_locked(
        self, snapshot_path: Path, snapshot_id: str, manifest: dict[str, Any]
    ) -> PublicationRecord:
        digest = snapshot_id.removeprefix("ir1:")
        if not _HEX_SHA256.fullmatch(digest):
            raise PublicationError("Локальный snapshot ID не является SHA-256")
        if manifest.get("snapshot_id") != snapshot_id:
            raise PublicationError("Snapshot manifest изменился после локальной проверки")
        for filename in _SNAPSHOT_FILES:
            body = (snapshot_path / filename).read_bytes()
            if filename == "manifest.json":
                valid = body == _canonical_json(manifest)
            else:
                descriptor = manifest.get("files", {}).get(filename)
                valid = (
                    isinstance(descriptor, dict)
                    and descriptor.get("bytes") == len(body)
                    and descriptor.get("sha256") == hashlib.sha256(body).hexdigest()
                )
            if not valid:
                raise PublicationError("Локальные snapshot bytes изменились после проверки")
            self._put_immutable(_object_key(self._prefix, "snapshots", digest, filename), body)

        current_key = _object_key(self._prefix, "current.json")
        previous: _Current | None
        try:
            previous = self._read_current(current_key)
        except FileNotFoundError:
            previous = None
        previous_id = previous.publication_id if previous else None
        sequence = previous.sequence + 1 if previous else 1
        published_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        record = PublicationRecord(
            publication_id=str(uuid4()),
            sequence=sequence,
            snapshot_id=snapshot_id,
            snapshot_sha256=digest,
            previous_publication_id=previous_id,
            published_at=published_at,
            actor=self._actor,
        )
        publication_body = _canonical_json(
            {
                "publication_id": record.publication_id,
                "sequence": record.sequence,
                "snapshot_id": record.snapshot_id,
                "snapshot_sha256": record.snapshot_sha256,
                "previous_publication_id": record.previous_publication_id,
                "published_at": record.published_at,
                "actor": record.actor,
            }
        )
        publication_key = _object_key(self._prefix, "publications", f"{record.publication_id}.json")
        self._put_immutable(publication_key, publication_body)
        self._verify_exact_remote_bytes(publication_key, publication_body)
        self._write_pending(record, previous)
        resumed = self._resume_pending_locked()
        if resumed is None:
            raise PublicationError("Publication intent исчез до установки current pointer")
        return resumed

    def _read_current(self, key: str) -> _Current:
        raw = self._storage.get(key)
        current = _parse_current(raw)
        _publication_for_pointer(self._storage, self._prefix, current)
        return current

    def _put_immutable(self, key: str, body: bytes) -> None:
        try:
            self._storage.put(key, body, if_none_match=True)
        except ConditionalWriteConflictError:
            pass
        except UnsupportedConditionalWriteError:
            raise
        except Exception:
            # Ответ PUT мог потеряться после сохранения объекта: сверяем GET.
            pass
        self._verify_exact_remote_bytes(key, body)

    def _verify_exact_remote_bytes(self, key: str, expected: bytes) -> None:
        try:
            actual = self._storage.get(key).body
        except Exception as exc:
            raise PublicationError("Не удалось прочитать remote object для проверки") from exc
        if actual != expected:
            raise PublicationError("Remote bytes не совпадают с проверенным локальным объектом")
