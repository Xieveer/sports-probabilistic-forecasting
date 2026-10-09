"""Контракт публикации registry поверх условного Object Storage."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sports_forecast.deploy.registry_publish import Boto3RegistryStorage, RegistryStorageError
from sports_forecast.deploy.registry_publish_cli import probe_conditional_writes
from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    PublicationError,
    RegistryPublisher,
    StorageObject,
    UnsupportedConditionalWriteError,
    download_current_publication,
    download_publication_snapshot,
    read_publication_by_id,
)
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.snapshot import export_registry_snapshot


@dataclass
class _Entry:
    body: bytes
    etag: str


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, _Entry] = {}
        self.fail_next_current_after_write = False
        self.fail_next_current_before_write = False
        self.reject_conditionals = False
        self.corrupt_reads: set[str] = set()
        self.race_current_body: bytes | None = None
        self.current_reads = 0
        self.fail_next_current_get = False
        self.fail_current_get_after_next_put = False
        self.current_puts = 0
        self.get_keys: list[str] = []
        self.bytes_returned: dict[str, int] = {}

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        self.get_keys.append(key)
        if key.endswith("/current.json"):
            self.current_reads += 1
        if key.endswith("/current.json") and self.fail_next_current_get:
            self.fail_next_current_get = False
            raise TimeoutError("read outcome unavailable")
        entry = self.objects.get(key)
        if entry is None:
            raise FileNotFoundError(key)
        body = entry.body + (b"corrupt" if key in self.corrupt_reads else b"")
        if max_bytes is not None and len(body) > max_bytes:
            raise PublicationError("test transport enforced max_bytes before reading")
        self.bytes_returned[key] = self.bytes_returned.get(key, 0) + len(body)
        return StorageObject(body=body, etag=entry.etag)

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        if key.endswith("/current.json"):
            self.current_puts += 1
            if self.fail_current_get_after_next_put:
                self.fail_next_current_get = True
                self.fail_current_get_after_next_put = False
        if self.reject_conditionals and (if_match is not None or if_none_match):
            raise UnsupportedConditionalWriteError("conditional write unsupported")
        current = self.objects.get(key)
        if if_none_match and current is not None:
            raise ConditionalWriteConflictError("object exists")
        if if_match is not None and (current is None or current.etag != if_match):
            raise ConditionalWriteConflictError("etag changed")
        if key.endswith("/current.json") and self.race_current_body is not None:
            raced = self.race_current_body
            self.race_current_body = None
            raced_etag = hashlib.md5(raced, usedforsecurity=False).hexdigest()
            self.objects[key] = _Entry(raced, raced_etag)
            raise ConditionalWriteConflictError("another publisher won CAS")
        if key.endswith("/current.json") and self.fail_next_current_before_write:
            self.fail_next_current_before_write = False
            raise TimeoutError("request outcome unavailable")
        etag = hashlib.md5(body, usedforsecurity=False).hexdigest()
        self.objects[key] = _Entry(body, etag)
        if key.endswith("/current.json") and self.fail_next_current_after_write:
            self.fail_next_current_after_write = False
            raise TimeoutError("response lost after remote write")
        return etag


def _snapshot(tmp_path: Path, name: str, entity_name: str = "") -> Path:
    registry = EntityRegistry(tmp_path / f"{name}.sqlite")
    registry.initialize()
    if entity_name:
        registry.create_entity("tournament", entity_name, sport="ice_hockey")
    return export_registry_snapshot(registry, tmp_path / name).path


def _publisher(tmp_path: Path, storage: _FakeStorage) -> RegistryPublisher:
    return RegistryPublisher(
        storage,
        prefix="entity-registry/v1",
        lock_path=tmp_path / "publisher.lock",
        actor="owner",
    )


def test_publish_verifies_every_remote_snapshot_file_before_current(tmp_path: Path) -> None:
    storage = _FakeStorage()
    path = _snapshot(tmp_path, "first")
    result = _publisher(tmp_path, storage).publish(path)

    assert result.sequence == 1
    current = json.loads(storage.objects["entity-registry/v1/current.json"].body)
    assert current["publication_id"] == result.publication_id
    assert current["snapshot_id"] == result.snapshot_id
    snapshot_prefix = f"entity-registry/v1/snapshots/{result.snapshot_sha256}"
    assert {
        key.rsplit("/", 1)[-1] for key in storage.objects if key.startswith(snapshot_prefix)
    } == {
        "manifest.json",
        "entities.jsonl",
        "designations.jsonl",
        "decisions.jsonl",
        "events.jsonl",
        "memberships.jsonl",
    }


def test_publication_actor_matches_server_installation_contract(tmp_path: Path) -> None:
    storage = _FakeStorage()
    valid_actor = "a" + "b" * 63
    valid = RegistryPublisher(
        storage,
        prefix="entity-registry/v1",
        lock_path=tmp_path / "valid.lock",
        actor=valid_actor,
    ).publish(_snapshot(tmp_path, "valid"))
    assert valid.actor == valid_actor

    with pytest.raises(ValueError, match="ASCII идентификатору"):
        RegistryPublisher(
            storage,
            prefix="entity-registry/v1",
            lock_path=tmp_path / "invalid.lock",
            actor="a" + "b" * 64,
        )


def test_publication_reader_rejects_actor_outside_installation_contract(
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    record = _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first"))
    key = f"entity-registry/v1/publications/{record.publication_id}.json"
    body = json.loads(storage.objects[key].body)
    body["actor"] = "owner with spaces"
    invalid = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    storage.objects[key] = _Entry(invalid, hashlib.md5(invalid, usedforsecurity=False).hexdigest())

    with pytest.raises(RuntimeError, match="недопустимые значения"):
        read_publication_by_id(
            storage,
            prefix="entity-registry/v1",
            publication_id=record.publication_id,
        )


def test_corrupt_remote_bytes_never_switch_current(tmp_path: Path) -> None:
    storage = _FakeStorage()
    path = _snapshot(tmp_path, "first")
    digest = path.name
    storage.corrupt_reads.add(f"entity-registry/v1/snapshots/{digest}/entities.jsonl")

    with pytest.raises(RuntimeError, match="Remote bytes"):
        _publisher(tmp_path, storage).publish(path)

    assert "entity-registry/v1/current.json" not in storage.objects


def test_existing_publication_remains_current_when_immutable_bytes_mismatch(
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    publisher = _publisher(tmp_path, storage)
    path = _snapshot(tmp_path, "first")
    published = publisher.publish(path)
    current_key = "entity-registry/v1/current.json"
    current_before = storage.objects[current_key].body
    key = f"entity-registry/v1/snapshots/{published.snapshot_sha256}/entities.jsonl"
    storage.corrupt_reads.add(key)

    with pytest.raises(RuntimeError, match="Remote bytes"):
        publisher.publish(path)

    assert storage.objects[current_key].body == current_before


def test_snapshot_mutated_during_upload_is_rejected(tmp_path: Path) -> None:
    path = _snapshot(tmp_path, "first")

    class MutatingStorage(_FakeStorage):
        def put(
            self,
            key: str,
            body: bytes,
            *,
            if_match: str | None = None,
            if_none_match: bool = False,
        ) -> str:
            etag = super().put(key, body, if_match=if_match, if_none_match=if_none_match)
            if key.endswith("/manifest.json"):
                (path / "entities.jsonl").write_bytes(b"mutated after validation\n")
            return etag

    storage = MutatingStorage()

    with pytest.raises(RuntimeError, match="snapshot bytes изменились после проверки"):
        _publisher(tmp_path, storage).publish(path)

    assert "entity-registry/v1/current.json" not in storage.objects


def test_pointer_unknown_put_outcome_is_resolved_by_reading_current(tmp_path: Path) -> None:
    storage = _FakeStorage()
    storage.fail_next_current_after_write = True

    result = _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first"))

    assert result.sequence == 1
    assert (
        json.loads(storage.objects["entity-registry/v1/current.json"].body)["publication_id"]
        == result.publication_id
    )


def test_pointer_unknown_put_without_remote_commit_stops_safely(tmp_path: Path) -> None:
    storage = _FakeStorage()
    storage.fail_next_current_before_write = True

    with pytest.raises(RuntimeError, match="Результат повтора неизвестен"):
        _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first"))

    assert "entity-registry/v1/current.json" not in storage.objects


def test_double_unknown_outcome_resumes_same_publication_after_restart(tmp_path: Path) -> None:
    storage = _FakeStorage()
    storage.fail_next_current_after_write = True
    storage.fail_current_get_after_next_put = True
    publisher = _publisher(tmp_path, storage)
    path = _snapshot(tmp_path, "first", "Tournament One")

    with pytest.raises(RuntimeError, match="intent сохранён"):
        publisher.publish(path)

    assert publisher.pending_intent_path.is_file()
    pending_id = json.loads(publisher.pending_intent_path.read_bytes())["record"]["publication_id"]
    resumed = _publisher(tmp_path, storage).resume_pending()

    assert resumed is not None
    assert resumed.publication_id == pending_id
    assert resumed.sequence == 1
    assert not publisher.pending_intent_path.exists()


def test_resume_does_not_publish_pointer_without_valid_remote_publication_record(
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    storage.fail_next_current_before_write = True
    storage.fail_current_get_after_next_put = True
    publisher = _publisher(tmp_path, storage)
    path = _snapshot(tmp_path, "first", "Tournament One")

    with pytest.raises(RuntimeError, match="intent сохранён"):
        publisher.publish(path)

    pending = json.loads(publisher.pending_intent_path.read_bytes())
    publication_id = pending["record"]["publication_id"]
    publication_key = f"entity-registry/v1/publications/{publication_id}.json"
    del storage.objects[publication_key]
    current_puts_before_retry = storage.current_puts

    with pytest.raises((FileNotFoundError, PublicationError)):
        publisher.resume_pending()

    assert storage.current_puts == current_puts_before_retry
    assert "entity-registry/v1/current.json" not in storage.objects
    assert publisher.pending_intent_path.is_file()


@pytest.mark.parametrize("budget_kind", ["too-small", "manifest-only"])
def test_snapshot_download_checks_total_budget_before_fetching_data_files(
    tmp_path: Path, budget_kind: str
) -> None:
    storage = _FakeStorage()
    record = _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first", "Tournament One"))
    digest = record.snapshot_sha256
    manifest_key = f"entity-registry/v1/snapshots/{digest}/manifest.json"
    manifest = storage.objects[manifest_key].body
    budget = 1 if budget_kind == "too-small" else len(manifest) + 1
    storage.get_keys.clear()
    storage.bytes_returned.clear()

    with pytest.raises(PublicationError, match="limit|превышает|max_bytes"):
        download_publication_snapshot(
            storage,
            prefix="entity-registry/v1",
            publication_id=record.publication_id,
            destination=tmp_path / "limited-download",
            max_bytes=budget,
        )

    snapshot_data_keys = {
        key
        for key in storage.get_keys
        if key.startswith(f"entity-registry/v1/snapshots/{digest}/")
        and not key.endswith("/manifest.json")
    }
    assert not snapshot_data_keys
    assert (
        sum(
            size
            for key, size in storage.bytes_returned.items()
            if key.startswith(f"entity-registry/v1/snapshots/{digest}/")
        )
        <= budget
    )


def test_cached_snapshot_download_checks_budget_before_verification(
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    record = _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first", "Tournament One"))
    destination = tmp_path / "cache"
    package = download_publication_snapshot(
        storage,
        prefix="entity-registry/v1",
        publication_id=record.publication_id,
        destination=destination,
    )
    storage.get_keys.clear()

    with pytest.raises(PublicationError, match="cached snapshot|Cached snapshot"):
        download_publication_snapshot(
            storage,
            prefix="entity-registry/v1",
            publication_id=record.publication_id,
            destination=destination,
            max_bytes=1,
        )

    assert package.is_dir()
    assert not any("/snapshots/" in key for key in storage.get_keys)


def test_conflicting_current_cas_does_not_overwrite_competing_publication(tmp_path: Path) -> None:
    storage = _FakeStorage()
    publisher = _publisher(tmp_path, storage)
    first = publisher.publish(_snapshot(tmp_path, "first"))
    original = storage.objects["entity-registry/v1/current.json"].body
    path = _snapshot(tmp_path, "second", "Tournament Two")
    storage.race_current_body = b'{"sequence":99}'

    with pytest.raises(ConditionalWriteConflictError):
        publisher.publish(path)

    assert storage.objects["entity-registry/v1/current.json"].body == b'{"sequence":99}'
    assert original != storage.objects["entity-registry/v1/current.json"].body
    assert first.sequence == 1
    assert publisher.pending_intent_path.is_file()


def test_unsupported_conditional_writes_fail_closed(tmp_path: Path) -> None:
    storage = _FakeStorage()
    storage.reject_conditionals = True

    with pytest.raises(UnsupportedConditionalWriteError):
        _publisher(tmp_path, storage).publish(_snapshot(tmp_path, "first"))

    assert "entity-registry/v1/current.json" not in storage.objects


def test_rollback_is_a_new_publication_with_higher_sequence(tmp_path: Path) -> None:
    storage = _FakeStorage()
    publisher = _publisher(tmp_path, storage)
    first_path = _snapshot(tmp_path, "first", "Tournament One")
    first = publisher.publish(first_path)
    second = publisher.publish(_snapshot(tmp_path, "second", "Tournament Two"))

    rollback = publisher.publish(first_path)

    assert first.snapshot_id == rollback.snapshot_id
    assert second.snapshot_id != rollback.snapshot_id
    assert rollback.sequence == second.sequence + 1
    assert rollback.previous_publication_id == second.publication_id


def test_publication_chain_can_be_read_and_downloaded_by_immutable_id(tmp_path: Path) -> None:
    storage = _FakeStorage()
    publisher = _publisher(tmp_path, storage)
    first_path = _snapshot(tmp_path, "first", "Tournament One")
    first = publisher.publish(first_path)
    second = publisher.publish(_snapshot(tmp_path, "second", "Tournament Two"))

    previous = read_publication_by_id(
        storage,
        prefix="entity-registry/v1",
        publication_id=second.previous_publication_id or "",
    )
    downloaded_path = download_publication_snapshot(
        storage,
        prefix="entity-registry/v1",
        publication_id=previous.publication_id,
        destination=tmp_path / "downloaded",
    )

    assert previous == first
    assert downloaded_path.name == first.snapshot_sha256
    assert (downloaded_path / "manifest.json").is_file()


def test_download_current_reads_pointer_once_and_verifies_selected_generation(
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    published = _publisher(tmp_path, storage).publish(
        _snapshot(tmp_path, "first", "Tournament One")
    )
    storage.current_reads = 0

    downloaded = download_current_publication(
        storage,
        prefix="entity-registry/v1",
        destination=tmp_path / "downloaded",
    )

    assert downloaded.record == published
    assert downloaded.snapshot_path.name == published.snapshot_sha256
    assert storage.current_reads == 1


def test_endpoint_contract_probe_checks_both_conditional_write_forms() -> None:
    storage = _FakeStorage()

    result = probe_conditional_writes(storage, prefix="probe-root")

    assert result["status"] == "supported"
    assert len(storage.objects) == 1
    assert b'"version": 2' in next(iter(storage.objects.values())).body


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.last_put: dict[str, object] = {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        if Key not in self.objects:
            raise _ClientError("NoSuchKey", 404)
        body, etag = self.objects[Key]
        return {"Body": io.BytesIO(body), "ETag": f'"{etag}"', "ContentLength": len(body)}

    def put_object(self, **params: object) -> dict[str, str]:
        self.last_put = params
        key = str(params["Key"])
        body = params["Body"]
        if not isinstance(body, bytes):
            raise TypeError("Body должен быть bytes")
        previous = self.objects.get(key)
        if "IfNoneMatch" in params and previous is not None:
            raise _ClientError("PreconditionFailed", 412)
        if "IfMatch" in params and (previous is None or params["IfMatch"] != f'"{previous[1]}"'):
            raise _ClientError("PreconditionFailed", 412)
        etag = hashlib.md5(body, usedforsecurity=False).hexdigest()
        self.objects[key] = (body, etag)
        return {"ETag": f'"{etag}"'}


class _ClientError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


def test_boto3_transport_always_sends_one_conditional_header() -> None:
    client = _FakeS3Client()
    storage = Boto3RegistryStorage(
        endpoint="https://storage.example",
        bucket="registry",
        access_key_id="test-key",
        secret_access_key="test-secret",
        client=client,
    )

    etag = storage.put("immutable/object.json", b"{}", if_none_match=True)
    assert client.last_put["IfNoneMatch"] == "*"
    assert storage.get("immutable/object.json").etag == etag
    pointer_etag = storage.put("current.json", b'{"v":1}', if_none_match=True)
    storage.put("current.json", b'{"v":2}', if_match=pointer_etag)
    assert client.last_put["IfMatch"] == f'"{pointer_etag}"'
    assert "IfNoneMatch" not in client.last_put


def test_boto3_transport_rejects_endpoint_without_conditional_put_support() -> None:
    class UnsupportedClient(_FakeS3Client):
        def put_object(self, **params: object) -> dict[str, str]:
            del params
            raise _ClientError("NotImplemented", 501)

    storage = Boto3RegistryStorage(
        endpoint="https://storage.example",
        bucket="registry",
        access_key_id="test-key",
        secret_access_key="test-secret",
        client=UnsupportedClient(),
    )

    with pytest.raises(UnsupportedConditionalWriteError):
        storage.put("current.json", b"{}", if_none_match=True)


def test_environment_configuration_error_does_not_echo_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SF_OBJECT_STORAGE_SECRET_ACCESS_KEY", "private-value")
    with pytest.raises(RegistryStorageError) as error:
        Boto3RegistryStorage.from_environment()
    assert "private-value" not in str(error.value)


def test_environment_supports_docker_secret_files_without_logging_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import boto3  # type: ignore[import-untyped]

    access_file = tmp_path / "access-key"
    secret_file = tmp_path / "secret-key"
    access_file.write_text("file-access-key\n", encoding="utf-8")
    secret_file.write_text("file-secret-value\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_client(*args: object, **kwargs: object) -> _FakeS3Client:
        captured.update(kwargs)
        return _FakeS3Client()

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setenv("SF_OBJECT_STORAGE_ENDPOINT", "https://storage.example")
    monkeypatch.setenv("SF_OBJECT_STORAGE_BUCKET", "registry")
    # runtime-entrypoint.sh оставляет _FILE и экспортирует прочитанное значение.
    monkeypatch.setenv("SF_OBJECT_STORAGE_ACCESS_KEY_ID", "file-access-key")
    monkeypatch.setenv("SF_OBJECT_STORAGE_SECRET_ACCESS_KEY", "file-secret-value")
    monkeypatch.setenv("SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE", str(access_file))
    monkeypatch.setenv("SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE", str(secret_file))

    Boto3RegistryStorage.from_environment()

    assert captured["aws_access_key_id"] == "file-access-key"
    assert captured["aws_secret_access_key"] == "file-secret-value"
    config = captured["config"]
    assert config.connect_timeout == 5
    assert config.read_timeout == 120
    assert config.retries["max_attempts"] == 3


def test_conflicting_direct_and_file_credentials_are_rejected_without_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / "secret-key"
    secret_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("SF_OBJECT_STORAGE_ACCESS_KEY_ID", "private-direct-value")
    monkeypatch.setenv("SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE", str(secret_file))

    with pytest.raises(RegistryStorageError) as error:
        Boto3RegistryStorage.from_environment()

    assert "private-direct-value" not in str(error.value)
