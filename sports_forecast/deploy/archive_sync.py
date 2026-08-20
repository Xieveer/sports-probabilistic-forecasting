"""Отдельный verified transport immutable operational archive в Object Storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sports_forecast.deploy.serving_data import (
    ArchiveArtifact,
    safe_archive_member_path,
    verify_archive,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_ARTIFACT_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArchiveSyncError(RuntimeError):
    """Upload либо remote verification operational archive не выполнены."""


class ObjectStorage(Protocol):
    """Минимальный контракт отдельного sync service account."""

    def upload(self, source: Path, key: str) -> None: ...

    def download(self, key: str, destination: Path) -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...


@dataclass(frozen=True)
class ArchiveSyncResult:
    """Проверенный результат синхронизации одного immutable artifact."""

    artifact_id: str
    status: str


class Boto3ObjectStorage:
    """S3-совместимое хранилище для отдельного sync process, не Worker."""

    def __init__(
        self, *, endpoint: str, bucket: str, access_key_id: str, secret_access_key: str
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - зависит от отдельного sync image
            raise ArchiveSyncError("Для archive sync нужен отдельный образ с boto3") from exc
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    @classmethod
    def from_environment(cls) -> Boto3ObjectStorage:
        """Собрать sync-only client из обязательных переменных окружения."""
        names = (
            "SF_OBJECT_STORAGE_ENDPOINT",
            "SF_OBJECT_STORAGE_BUCKET",
            "SF_OBJECT_STORAGE_ACCESS_KEY_ID",
            "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        )
        values = {name: os.environ.get(name, "") for name in names}
        if any(not value for value in values.values()):
            raise ArchiveSyncError("Не заданы credentials отдельного Object Storage sync process")
        return cls(
            endpoint=values["SF_OBJECT_STORAGE_ENDPOINT"],
            bucket=values["SF_OBJECT_STORAGE_BUCKET"],
            access_key_id=values["SF_OBJECT_STORAGE_ACCESS_KEY_ID"],
            secret_access_key=values["SF_OBJECT_STORAGE_SECRET_ACCESS_KEY"],
        )

    def upload(self, source: Path, key: str) -> None:
        self._client.upload_file(str(source), self._bucket, key)

    def download(self, key: str, destination: Path) -> None:
        self._client.download_file(self._bucket, key, str(destination))

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        request: dict[str, str] = {"Bucket": self._bucket, "Prefix": prefix}
        while True:
            response = self._client.list_objects_v2(**request)
            keys.extend(str(item["Key"]) for item in response.get("Contents", []) if "Key" in item)
            if not response.get("IsTruncated"):
                return keys
            token = response.get("NextContinuationToken")
            if not isinstance(token, str) or not token:
                raise ArchiveSyncError(
                    "Object Storage вернул truncated listing без continuation token"
                )
            request["ContinuationToken"] = token


def _validate_artifact_id(artifact_id: str) -> None:
    """Отклонить ID, который может выйти за пределы local download root."""
    if not _ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ArchiveSyncError("Небезопасный artifact_id")


def _state_path(state_root: Path, artifact_id: str) -> Path:
    return state_root / f"{artifact_id}.json"


def _write_state(state_root: Path, artifact_id: str, status: str) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    target = _state_path(state_root, artifact_id)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps({"artifact_id": artifact_id, "status": status}) + "\n", encoding="utf-8"
    )
    temporary.replace(target)


def sync_operational_archive(
    archive_path: Path,
    state_root: Path,
    storage: ObjectStorage,
    *,
    prefix: str = "operational-archive",
) -> ArchiveSyncResult:
    """Загрузить artifact и сверить каждый remote object с локальным checksum.

    Worker этот модуль не вызывает: credentials принадлежат отдельному sync process.
    При любой ошибке archive остаётся на staging, а durable state получает ``failed``.
    """
    artifact: ArchiveArtifact = verify_archive(archive_path)
    try:
        manifest = json.loads((artifact.path / "manifest.json").read_text(encoding="utf-8"))
        relative_paths = ["manifest.json", *[str(item["path"]) for item in manifest["files"]]]
        base = f"{prefix.rstrip('/')}/{artifact.artifact_id}"
        for relative in relative_paths:
            storage.upload(artifact.path / relative, f"{base}/{relative}")
        with tempfile.TemporaryDirectory(prefix="archive-sync-verify-") as raw_tmp:
            temporary = Path(raw_tmp)
            for relative in relative_paths:
                remote_copy = temporary / relative
                remote_copy.parent.mkdir(parents=True, exist_ok=True)
                storage.download(f"{base}/{relative}", remote_copy)
                if remote_copy.read_bytes() != (artifact.path / relative).read_bytes():
                    raise ArchiveSyncError(f"Remote object differs: {relative}")
        _write_state(state_root, artifact.artifact_id, "verified")
        logger.info("Operational archive remote-verified artifact_id=%s", artifact.artifact_id)
        return ArchiveSyncResult(artifact.artifact_id, "verified")
    except Exception as exc:
        _write_state(state_root, artifact.artifact_id, "failed")
        if isinstance(exc, ArchiveSyncError):
            raise
        raise ArchiveSyncError(f"Operational archive sync failed: {type(exc).__name__}") from exc


def pull_verified_archive(
    artifact_id: str,
    download_root: Path,
    storage: ObjectStorage,
    *,
    prefix: str = "operational-archive",
) -> Path:
    """Read-only скачать один artifact по ID и проверить его до local import/DVC."""
    _validate_artifact_id(artifact_id)
    destination = download_root / artifact_id
    if destination.exists():
        verify_archive(destination)
        return destination
    base = f"{prefix.rstrip('/')}/{artifact_id}"
    download_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archive-pull-", dir=download_root) as raw_tmp:
        stage = Path(raw_tmp) / artifact_id
        stage.mkdir()
        try:
            storage.download(f"{base}/manifest.json", stage / "manifest.json")
            manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
            for item in manifest["files"]:
                relative = str(item["path"])
                local_file = safe_archive_member_path(stage, relative)
                local_file.parent.mkdir(parents=True, exist_ok=True)
                storage.download(f"{base}/{relative}", local_file)
            verify_archive(stage)
            stage.replace(destination)
        except Exception as exc:
            if isinstance(exc, ArchiveSyncError):
                raise
            raise ArchiveSyncError(f"Local archive pull failed: {type(exc).__name__}") from exc
    return destination


def pull_latest_verified_archive(
    download_root: Path,
    storage: ObjectStorage,
    *,
    prefix: str = "operational-archive/nhl-source-state/v1",
) -> Path:
    """Получить последний проверяемый source-state без remote mutable pointer.

    Неполный или повреждённый newest artifact пропускается; выбирается
    предыдущий manifest, прошедший полную checksum-проверку.
    """
    base = prefix.rstrip("/")
    manifests = [key for key in storage.list_keys(f"{base}/") if key.endswith("/manifest.json")]
    candidates: list[tuple[str, str]] = []
    for key in manifests:
        artifact_id = key[len(base) + 1 : -len("/manifest.json")]
        if artifact_id:
            with tempfile.TemporaryDirectory(prefix="archive-latest-manifest-") as raw_tmp:
                manifest_path = Path(raw_tmp) / "manifest.json"
                try:
                    storage.download(key, manifest_path)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    created_at = str(manifest.get("created_at", ""))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
            candidates.append((created_at, artifact_id))
    for _created_at, artifact_id in sorted(candidates, reverse=True):
        try:
            return pull_verified_archive(artifact_id, download_root, storage, prefix=prefix)
        except (ArchiveSyncError, OSError, ValueError):
            continue
    raise ArchiveSyncError(f"Нет verified source-state artifact под prefix={prefix}")
