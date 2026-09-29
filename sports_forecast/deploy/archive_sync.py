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
_LEGACY_VERIFICATION_PREFIXES = frozenset(
    {"operational-archive", "operational-archive/nhl-source-state/v1"}
)


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
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - зависит от отдельного sync image
            raise ArchiveSyncError("Для archive sync нужен отдельный образ с boto3") from exc
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                connect_timeout=5,
                read_timeout=20,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
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


def _write_state(state_root: Path, artifact_id: str, status: str, prefix: str) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    target = _state_path(state_root, artifact_id)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps({"artifact_id": artifact_id, "status": status, "prefix": prefix.rstrip("/")})
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _is_durably_verified(state_root: Path, artifact_id: str, prefix: str) -> bool:
    """Доверять только точной durable записи проверки архива в том же prefix."""
    try:
        state = json.loads(_state_path(state_root, artifact_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(state, dict)
        and state.get("artifact_id") == artifact_id
        and state.get("status") == "verified"
        and state.get("prefix") == prefix.rstrip("/")
    )


def _has_legacy_verified_state(state_root: Path, artifact_id: str) -> bool:
    """Найти старую verified-запись без идентификатора Object Storage prefix."""
    try:
        state = json.loads(_state_path(state_root, artifact_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(state, dict)
        and state.get("artifact_id") == artifact_id
        and state.get("status") == "verified"
        and "prefix" not in state
    )


def _files_equal(first: Path, second: Path) -> bool:
    """Сравнить файлы побайтово без загрузки целого архива в память."""
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as first_stream, second.open("rb") as second_stream:
        while True:
            first_chunk = first_stream.read(1024 * 1024)
            second_chunk = second_stream.read(1024 * 1024)
            if first_chunk != second_chunk:
                return False
            if not first_chunk:
                return True


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
    normalized_prefix = prefix.rstrip("/")
    if _is_durably_verified(state_root, artifact.artifact_id, normalized_prefix):
        logger.info(
            "Operational archive already remote-verified artifact_id=%s", artifact.artifact_id
        )
        return ArchiveSyncResult(artifact.artifact_id, "verified")
    legacy_verified = (
        normalized_prefix in _LEGACY_VERIFICATION_PREFIXES
        and _has_legacy_verified_state(state_root, artifact.artifact_id)
    )
    try:
        manifest = json.loads((artifact.path / "manifest.json").read_text(encoding="utf-8"))
        relative_paths = ["manifest.json", *[str(item["path"]) for item in manifest["files"]]]
        base = f"{normalized_prefix}/{artifact.artifact_id}"
        if legacy_verified:
            try:
                remote_keys = storage.list_keys(f"{base}/")
            except Exception as exc:
                logger.warning(
                    "Не удалось подтвердить legacy verified archive listing; "
                    "выполняется полная проверка: %s",
                    type(exc).__name__,
                )
            else:
                expected_keys = {f"{base}/{relative}" for relative in relative_paths}
                if set(remote_keys) == expected_keys:
                    try:
                        state_root.mkdir(parents=True, exist_ok=True)
                        with tempfile.TemporaryDirectory(
                            prefix="archive-sync-legacy-", dir=state_root
                        ) as raw_tmp:
                            remote_manifest = Path(raw_tmp) / "manifest.json"
                            storage.download(f"{base}/manifest.json", remote_manifest)
                            remote_matches = _files_equal(
                                remote_manifest, artifact.path / "manifest.json"
                            )
                    except Exception as exc:
                        logger.warning(
                            "Не удалось подтвердить legacy verified manifest; "
                            "выполняется полная проверка: %s",
                            type(exc).__name__,
                        )
                    else:
                        if remote_matches:
                            _write_state(
                                state_root, artifact.artifact_id, "verified", normalized_prefix
                            )
                            logger.info(
                                "Operational archive legacy verification migrated artifact_id=%s",
                                artifact.artifact_id,
                            )
                            return ArchiveSyncResult(artifact.artifact_id, "verified")
        for relative in relative_paths:
            storage.upload(artifact.path / relative, f"{base}/{relative}")
        state_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="archive-sync-verify-", dir=state_root) as raw_tmp:
            temporary = Path(raw_tmp)
            for relative in relative_paths:
                remote_copy = temporary / relative
                remote_copy.parent.mkdir(parents=True, exist_ok=True)
                storage.download(f"{base}/{relative}", remote_copy)
                if not _files_equal(remote_copy, artifact.path / relative):
                    raise ArchiveSyncError(f"Remote object differs: {relative}")
        _write_state(state_root, artifact.artifact_id, "verified", normalized_prefix)
        logger.info("Operational archive remote-verified artifact_id=%s", artifact.artifact_id)
        return ArchiveSyncResult(artifact.artifact_id, "verified")
    except Exception as exc:
        _write_state(state_root, artifact.artifact_id, "failed", normalized_prefix)
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
