"""Контракт отдельного verified sync operational archive."""

from __future__ import annotations

import hashlib
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
    def __init__(self, *, fail_upload: bool = False, corrupt_download: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_upload = fail_upload
        self.corrupt_download = corrupt_download

    def upload(self, source: Path, key: str) -> None:
        if self.fail_upload:
            raise OSError("network unavailable")
        self.objects[key] = source.read_bytes()

    def download(self, key: str, destination: Path) -> None:
        value = self.objects[key]
        destination.write_bytes(
            b"corrupt" if self.corrupt_download and key.endswith("data.json") else value
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


def test_sync_failure_keeps_staging_and_writes_retryable_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")

    with pytest.raises(ArchiveSyncError):
        sync_operational_archive(artifact.path, tmp_path / "state", _FakeStorage(fail_upload=True))

    assert artifact.path.exists()
    assert '"status": "failed"' in (tmp_path / "state" / f"{artifact.artifact_id}.json").read_text()


def test_sync_remote_verifies_all_files_before_success(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    storage = _FakeStorage()

    result = sync_operational_archive(artifact.path, tmp_path / "state", storage)

    assert result.status == "verified"
    assert f"operational-archive/{artifact.artifact_id}/manifest.json" in storage.objects


def test_remote_corruption_keeps_staging_and_failed_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    artifact = archive_snapshot(source, tmp_path / "staging")
    state_root = tmp_path / "state"

    with pytest.raises(ArchiveSyncError, match="differs"):
        sync_operational_archive(artifact.path, state_root, _FakeStorage(corrupt_download=True))

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
