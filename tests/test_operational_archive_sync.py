"""Контракт отдельного verified sync operational archive."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from sports_forecast.deploy.archive_sync import (
    ArchiveSyncError,
    Boto3ObjectStorage,
    pull_latest_verified_archive,
    pull_verified_archive,
    sync_operational_archive,
)
from sports_forecast.deploy.serving_data import archive_snapshot


class _FakeStorage:
    def __init__(
        self,
        *,
        fail_upload: bool = False,
        corrupt_download: bool = False,
        corruption_payload: bytes = b"corrupt",
    ) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_upload = fail_upload
        self.corrupt_download = corrupt_download
        self.corruption_payload = corruption_payload

    def upload(self, source: Path, key: str) -> None:
        if self.fail_upload:
            raise OSError("network unavailable")
        self.objects[key] = source.read_bytes()

    def download(self, key: str, destination: Path) -> None:
        value = self.objects[key]
        destination.write_bytes(
            self.corruption_payload
            if self.corrupt_download and key.endswith("data.json")
            else value
        )

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


def test_boto_listing_follows_continuation_tokens() -> None:
    class _PagedClient:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def list_objects_v2(self, **kwargs: str) -> dict[str, object]:
            token = kwargs.get("ContinuationToken")
            self.calls.append(token)
            if token is None:
                return {
                    "Contents": [{"Key": "a"}],
                    "IsTruncated": True,
                    "NextContinuationToken": "next",
                }
            return {"Contents": [{"Key": "b"}], "IsTruncated": False}

    client = _PagedClient()
    storage = object.__new__(Boto3ObjectStorage)
    storage._bucket = "bucket"
    storage._client = client

    assert storage.list_keys("prefix/") == ["a", "b"]
    assert client.calls == [None, "next"]


def test_boto_client_uses_bounded_timeouts_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3
    from botocore.config import Config

    captured: dict[str, object] = {}
    original_config = Config

    def client_factory(service: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    def config_factory(**kwargs: object) -> Config:
        captured["retry_config"] = kwargs
        return original_config(**kwargs)

    monkeypatch.setattr(boto3, "client", client_factory)
    monkeypatch.setattr("botocore.config.Config", config_factory)

    Boto3ObjectStorage(
        endpoint="https://storage.example",
        bucket="bucket",
        access_key_id="id",
        secret_access_key="secret",
    )

    assert captured["retry_config"] == {
        "connect_timeout": 5,
        "read_timeout": 20,
        "retries": {"mode": "standard", "total_max_attempts": 3},
    }


def test_sync_failure_keeps_staging_and_writes_retryable_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")

    state_root = tmp_path / "state"
    with pytest.raises(ArchiveSyncError):
        sync_operational_archive(artifact.path, state_root, _FakeStorage(fail_upload=True))

    assert artifact.path.exists()
    state_path = state_root / f"{artifact.artifact_id}.json"
    assert '"status": "failed"' in state_path.read_text()

    retry_storage = _FakeStorage()
    retry_result = sync_operational_archive(artifact.path, state_root, retry_storage)

    assert retry_result.status == "verified"
    assert f"operational-archive/{artifact.artifact_id}/manifest.json" in retry_storage.objects


def test_sync_remote_verifies_all_files_before_success(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    storage = _FakeStorage()

    result = sync_operational_archive(artifact.path, tmp_path / "state", storage)

    assert result.status == "verified"
    assert f"operational-archive/{artifact.artifact_id}/manifest.json" in storage.objects


def test_sync_reuses_durable_verified_state_without_remote_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / f"{artifact.artifact_id}.json").write_text(
        f'{{"artifact_id":"{artifact.artifact_id}","status":"verified",'
        '"prefix":"operational-archive"}\n',
        encoding="utf-8",
    )

    class UnavailableStorage:
        def upload(self, source: Path, key: str) -> None:
            raise AssertionError("Verified artifact must not be uploaded again")

        def download(self, key: str, destination: Path) -> None:
            raise AssertionError("Verified artifact must not be downloaded again")

        def list_keys(self, prefix: str) -> list[str]:
            raise AssertionError("Sync must not list remote objects")

    result = sync_operational_archive(artifact.path, state_root, UnavailableStorage())

    assert result.status == "verified"


def test_sync_does_not_reuse_verification_from_another_prefix(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"
    storage = _FakeStorage()

    sync_operational_archive(artifact.path, state_root, storage, prefix="first-prefix")
    result = sync_operational_archive(artifact.path, state_root, storage, prefix="second-prefix")

    assert result.status == "verified"
    assert f"second-prefix/{artifact.artifact_id}/manifest.json" in storage.objects


@pytest.mark.parametrize(
    "prefix",
    ["operational-archive", "operational-archive/nhl-source-state/v1"],
)
def test_sync_migrates_legacy_verified_state_after_remote_key_confirmation(
    tmp_path: Path, prefix: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"
    underlying = _FakeStorage()
    sync_operational_archive(
        artifact.path,
        state_root,
        underlying,
        prefix=prefix,
    )
    state_path = state_root / f"{artifact.artifact_id}.json"
    state_path.write_text(
        f'{{"artifact_id":"{artifact.artifact_id}","status":"verified"}}\n',
        encoding="utf-8",
    )

    class TrackingStorage:
        def __init__(self) -> None:
            self.list_calls = 0
            self.upload_calls = 0
            self.download_calls = 0

        def upload(self, source: Path, key: str) -> None:
            self.upload_calls += 1
            underlying.upload(source, key)

        def download(self, key: str, destination: Path) -> None:
            self.download_calls += 1
            underlying.download(key, destination)

        def list_keys(self, prefix: str) -> list[str]:
            self.list_calls += 1
            return underlying.list_keys(prefix)

    storage = TrackingStorage()
    result = sync_operational_archive(
        artifact.path,
        state_root,
        storage,
        prefix=prefix,
    )

    assert result.status == "verified"
    assert (storage.list_calls, storage.upload_calls, storage.download_calls) == (1, 0, 1)
    assert f'"prefix": "{prefix}"' in state_path.read_text()


def test_sync_does_not_trust_legacy_state_without_remote_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"
    prefix = "unrelated-prefix"
    underlying = _FakeStorage()
    sync_operational_archive(artifact.path, state_root, underlying, prefix=prefix)
    state_path = state_root / f"{artifact.artifact_id}.json"
    state_path.write_text(
        f'{{"artifact_id":"{artifact.artifact_id}","status":"verified"}}\n',
        encoding="utf-8",
    )

    class TrackingStorage:
        def __init__(self) -> None:
            self.list_calls = 0
            self.upload_calls = 0
            self.download_calls = 0

        def upload(self, source: Path, key: str) -> None:
            self.upload_calls += 1
            underlying.upload(source, key)

        def download(self, key: str, destination: Path) -> None:
            self.download_calls += 1
            underlying.download(key, destination)

        def list_keys(self, listing_prefix: str) -> list[str]:
            self.list_calls += 1
            return underlying.list_keys(listing_prefix)

    storage = TrackingStorage()

    result = sync_operational_archive(artifact.path, state_root, storage, prefix=prefix)

    assert result.status == "verified"
    assert (storage.list_calls, storage.upload_calls, storage.download_calls) == (0, 2, 2)
    assert f'"prefix": "{prefix}"' in state_path.read_text()


def test_sync_large_archive_does_not_read_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проверка большого объекта работает при запрете чтения файла целиком."""

    class StreamingStorage:
        def __init__(self) -> None:
            self.objects: dict[str, Path] = {}

        def upload(self, source: Path, key: str) -> None:
            self.objects[key] = source

        def download(self, key: str, destination: Path) -> None:
            shutil.copyfile(self.objects[key], destination)

        def list_keys(self, prefix: str) -> list[str]:
            return sorted(key for key in self.objects if key.startswith(prefix))

    source = tmp_path / "source"
    source.mkdir()
    with (source / "large.bin").open("wb") as stream:
        for _ in range(32):
            stream.write(b"x" * 65536)
    artifact = archive_snapshot(source, tmp_path / "staging")
    original_read_bytes = Path.read_bytes

    def bounded_read_bytes(path: Path) -> bytes:
        if path.stat().st_size > 1024 * 1024:
            raise AssertionError("Большой файл прочитан целиком")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", bounded_read_bytes)

    result = sync_operational_archive(artifact.path, tmp_path / "state", StreamingStorage())

    assert result.status == "verified"


def test_sync_downloads_remote_copy_under_state_root(tmp_path: Path) -> None:
    """Remote verification не расходует маленький production tmpfs."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"

    class TrackingStorage(_FakeStorage):
        def download(self, key: str, destination: Path) -> None:
            assert destination.is_relative_to(state_root)
            super().download(key, destination)

    result = sync_operational_archive(artifact.path, state_root, TrackingStorage())

    assert result.status == "verified"


@pytest.mark.parametrize("corruption_payload", [b"corrupt", b"[]"])
def test_remote_corruption_keeps_staging_and_failed_state(
    tmp_path: Path, corruption_payload: bytes
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"

    with pytest.raises(ArchiveSyncError, match="differs"):
        sync_operational_archive(
            artifact.path,
            state_root,
            _FakeStorage(corrupt_download=True, corruption_payload=corruption_payload),
        )

    assert artifact.path.exists()
    assert '"status": "failed"' in (state_root / f"{artifact.artifact_id}.json").read_text()


def test_local_pull_verifies_before_creating_training_import(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    storage = _FakeStorage()
    sync_operational_archive(artifact.path, tmp_path / "sync-state", storage)

    pulled = pull_verified_archive(artifact.artifact_id, tmp_path / "downloads", storage)

    assert (pulled / "data.json").read_text(encoding="utf-8") == "{}"


def test_local_pull_rejects_manifest_path_outside_staging(tmp_path: Path) -> None:
    """Недоверенный manifest не может записать файл за пределами local staging."""
    artifact_id = "sha256:unsafe"
    victim = tmp_path / "victim.txt"
    victim.write_text("safe", encoding="utf-8")
    storage = _FakeStorage()
    key = f"operational-archive/{artifact_id}/manifest.json"
    storage.objects[key] = (
        '{"schema_version":1,"artifact_id":"sha256:unsafe","created_at":"x",'
        f'"files":[{{"path":"{victim}","sha256":"{hashlib.sha256(b"pwned").hexdigest()}",'
        '"size":5}],"provenance":{}}'
    ).encode()
    storage.objects[f"operational-archive/{artifact_id}/{victim}"] = b"pwned"

    with pytest.raises(ArchiveSyncError):
        pull_verified_archive(artifact_id, tmp_path / "downloads", storage)

    assert victim.read_text(encoding="utf-8") == "safe"


def test_latest_source_state_skips_corrupt_newest_and_imports_previous(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("old", encoding="utf-8")
    old = archive_snapshot(source, tmp_path / "archive")
    storage = _FakeStorage()
    sync_operational_archive(
        old.path,
        tmp_path / "sync-state",
        storage,
        prefix="operational-archive/nhl-source-state/v1",
    )
    (source / "data.json").write_text("new", encoding="utf-8")
    newest = archive_snapshot(source, tmp_path / "archive")
    sync_operational_archive(
        newest.path,
        tmp_path / "sync-state",
        storage,
        prefix="operational-archive/nhl-source-state/v1",
    )
    storage.objects[f"operational-archive/nhl-source-state/v1/{newest.artifact_id}/data.json"] = (
        b"corrupt"
    )

    pulled = pull_latest_verified_archive(
        tmp_path / "downloads",
        storage,
        prefix="operational-archive/nhl-source-state/v1",
    )

    assert pulled.name == old.artifact_id
    assert (pulled / "data.json").read_text(encoding="utf-8") == "old"
