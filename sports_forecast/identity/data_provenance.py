"""Content-bound provenance для identity-resolution в parquet pipeline."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pandas as pd
import yaml

from sports_forecast.identity.snapshot import VerifiedRegistrySnapshot, verify_registry_snapshot


DATA_PROVENANCE_VERSION = 1
MAX_SIDECAR_BYTES = 64 * 1024 * 1024
MAX_SIDECAR_RESOLUTIONS = 2_000_000
IdentityStatus = Literal["resolved", "unresolved", "ambiguous", "conflict"]


@dataclass(frozen=True)
class IdentityRowResolution:
    """Результат разрешения одной строки ingest без provider payload."""

    row_id: str | None
    source_event_id: str
    status: IdentityStatus
    project_event_id: str | None
    reason: str


@dataclass(frozen=True)
class DatasetIdentityProvenance:
    """Проверенная связь parquet с immutable registry snapshot."""

    snapshot_id: str
    snapshot_sha256: str
    parquet_sha256: str
    dataset_row_count: int
    adapter_name: str
    source: str
    tournament: str
    resolutions: tuple[IdentityRowResolution, ...]
    snapshot: VerifiedRegistrySnapshot


def identity_sidecar_path(data_path: Path) -> Path:
    """Вернуть sidecar path для конкретного parquet файла."""
    return Path(f"{Path(data_path)}.identity.json")


def _identity_config(project_root: Path) -> dict[str, Any] | None:
    config_path = Path(project_root) / "conf" / "identity_registry.yaml"
    if not config_path.is_file():
        return None
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("enabled"), bool):
        raise ValueError("identity_registry.yaml должен содержать boolean enabled")
    return config


def _enabled_identity_tournaments(config: dict[str, Any]) -> list[str]:
    enabled = config.get("enabled_tournaments")
    adapters = config.get("adapters")
    if (
        not isinstance(enabled, list)
        or any(not isinstance(name, str) or not name.strip() for name in enabled)
        or len(enabled) != len(set(enabled))
    ):
        raise ValueError("Enabled identity mode требует уникальный список enabled_tournaments")
    if not isinstance(adapters, dict):
        raise ValueError("Enabled identity mode требует map adapters")
    for name in enabled:
        adapter = adapters.get(name)
        if not isinstance(adapter, dict):
            raise ValueError(f"Для enabled турнира {name} отсутствует identity adapter")
        required = ("source", "sport", "row_id", "event_id", "scheduled_at")
        if any(
            not isinstance(adapter.get(key), str) or not adapter[key].strip() for key in required
        ):
            raise ValueError(f"Identity adapter турнира {name} не содержит обязательные поля")
        if not any(isinstance(adapter.get(key), str) for key in ("home", "home_id")) or not any(
            isinstance(adapter.get(key), str) for key in ("away", "away_id")
        ):
            raise ValueError(f"Identity adapter турнира {name} не содержит home/away columns")
    return enabled


def identity_mode_for_tournament(project_root: Path, tournament_name: str) -> bool:
    """Проверить явный identity rollout и adapter для выбранного турнира."""
    config = _identity_config(project_root)
    if config is None or not config["enabled"]:
        return False
    enabled = _enabled_identity_tournaments(config)
    adapters = config["adapters"]
    if tournament_name not in enabled:
        return False
    if not isinstance(adapters.get(tournament_name), dict):
        raise ValueError(f"Для enabled турнира {tournament_name} отсутствует identity adapter")
    return True


def load_enabled_registry_snapshot(
    project_root: Path, *, tournament_name: str | None = None
) -> VerifiedRegistrySnapshot | None:
    """Загрузить один immutable archive pin либо вернуть None для legacy tournament."""
    config = _identity_config(project_root)
    if config is None:
        return None
    if not config["enabled"]:
        return None
    enabled = _enabled_identity_tournaments(config)
    if not enabled:
        return None
    if tournament_name is not None and tournament_name not in enabled:
        return None
    if tournament_name is not None and not identity_mode_for_tournament(
        project_root, tournament_name
    ):
        return None
    selected_path = config.get("selected_package_path")
    if not isinstance(selected_path, str) or not selected_path.strip():
        raise ValueError("Enabled identity mode требует selected_package_path")
    package_path = Path(project_root) / selected_path
    lock_path = package_path.parent.parent / f".{package_path.parent.name}.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            snapshot = verify_registry_snapshot(package_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    expected_snapshot_id = config.get("snapshot_id")
    if expected_snapshot_id is not None and snapshot.snapshot_id != expected_snapshot_id:
        raise ValueError("Установленный registry snapshot не совпадает с config pin")
    snapshot_root_value = config.get("snapshot_root")
    if not isinstance(snapshot_root_value, str) or not snapshot_root_value.strip():
        raise ValueError("Enabled identity mode требует snapshot_root")
    archive_path = Path(project_root) / snapshot_root_value / snapshot.projection_sha256
    archived = verify_registry_snapshot(archive_path)
    if archived.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Content-addressed archive не совпадает с выбранным package")
    return archived


def configured_snapshot_root(project_root: Path) -> Path:
    """Получить локальный корень установленных snapshot из проекта."""
    config_path = Path(project_root) / "conf" / "identity_registry.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("snapshot_root"), str):
        raise ValueError("identity_registry.yaml должен содержать snapshot_root")
    snapshot_root = config["snapshot_root"]
    return Path(project_root) / str(snapshot_root)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_ids(path: Path, column: str, *, allow_duplicates: bool = False) -> tuple[str, ...]:
    if not column.strip():
        raise ValueError("Колонка row ID обязательна")
    frame = pd.read_parquet(path, columns=[column])
    if column not in frame:
        raise ValueError("Parquet не содержит настроенную колонку row ID")
    if frame[column].isna().any():
        raise ValueError("Parquet содержит строку без provider row ID")
    row_ids = tuple(str(value).strip() for value in frame[column].tolist())
    if any(not row_id for row_id in row_ids):
        raise ValueError("Parquet содержит пустой provider row ID")
    if not allow_duplicates and len(set(row_ids)) != len(row_ids):
        raise ValueError("Provider row ID должен быть уникальным до long-format fanout")
    return row_ids


def _payload(
    data_path: Path,
    *,
    snapshot: VerifiedRegistrySnapshot,
    adapter_name: str,
    source: str,
    tournament: str,
    resolutions: tuple[IdentityRowResolution, ...],
    row_id_column: str,
    allow_duplicate_row_ids: bool,
) -> dict[str, Any]:
    if not all(value.strip() for value in (adapter_name, source, tournament)) or any(
        len(value) > limit
        for value, limit in ((adapter_name, 128), (source, 128), (tournament, 500))
    ):
        raise ValueError("Adapter, source и tournament обязательны")
    if snapshot.snapshot_id != f"ir1:{snapshot.projection_sha256}":
        raise ValueError("Registry snapshot не проверен")
    verified_snapshot = verify_registry_snapshot(snapshot.path)
    if verified_snapshot.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Registry snapshot изменился после проверки")
    snapshot = verified_snapshot
    actual_row_ids = _row_ids(data_path, row_id_column, allow_duplicates=allow_duplicate_row_ids)
    normalized_rows: dict[str, IdentityRowResolution] = {}
    for result in resolutions:
        if result.row_id is None or not str(result.row_id).strip() or len(str(result.row_id)) > 500:
            raise ValueError("Resolution не содержит provider row ID")
        row_id = str(result.row_id).strip()
        if row_id in normalized_rows:
            raise ValueError("Повторный provider row ID в identity results")
        if result.status not in {"resolved", "unresolved", "ambiguous", "conflict"}:
            raise ValueError("Неизвестный статус identity resolution")
        if result.status == "resolved" and not result.project_event_id:
            raise ValueError("Resolved identity result должен содержать project event UUID")
        if result.status == "resolved" and result.project_event_id not in {
            event.id for event in snapshot.event_snapshot.events
        }:
            raise ValueError("Resolved project event отсутствует в verified registry snapshot")
        if result.status != "resolved" and result.project_event_id is not None:
            raise ValueError("Неразрешённая identity result не должна содержать project event UUID")
        if not result.reason.strip() or len(result.reason) > 500:
            raise ValueError("Identity reason пустой или превышает допустимую длину")
        if len(result.source_event_id) > 500:
            raise ValueError("Source event ID превышает допустимую длину")
        normalized_rows[row_id] = IdentityRowResolution(
            row_id,
            result.source_event_id,
            result.status,
            result.project_event_id,
            result.reason,
        )
    if set(actual_row_ids) != set(normalized_rows):
        raise ValueError("Identity results не соответствуют provider row IDs parquet")
    return {
        "format": "sports-forecast-dataset-identity",
        "version": DATA_PROVENANCE_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256": snapshot.projection_sha256,
        "parquet_sha256": _sha256_file(data_path),
        "parquet_bytes": Path(data_path).stat().st_size,
        "dataset_row_count": len(actual_row_ids),
        "row_id_column": row_id_column,
        "allow_duplicate_row_ids": allow_duplicate_row_ids,
        "adapter_name": adapter_name,
        "source": source,
        "tournament": tournament,
        "resolutions": [result.__dict__ for _, result in sorted(normalized_rows.items())],
    }


def write_identity_provenance(
    data_path: Path,
    *,
    snapshot: VerifiedRegistrySnapshot,
    adapter_name: str,
    source: str,
    tournament: str,
    resolutions: tuple[IdentityRowResolution, ...],
    row_id_column: str = "id",
    allow_duplicate_row_ids: bool = False,
) -> Path:
    """Атомарно записать sidecar, связанный с точным parquet content hash."""
    payload = _payload(
        Path(data_path),
        snapshot=snapshot,
        adapter_name=adapter_name,
        source=source,
        tournament=tournament,
        resolutions=resolutions,
        row_id_column=row_id_column,
        allow_duplicate_row_ids=allow_duplicate_row_ids,
    )
    payload["provenance_sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
    sidecar = identity_sidecar_path(data_path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{sidecar.name}.", dir=sidecar.parent)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(_canonical_json(payload) + b"\n")
            target.flush()
            os.fsync(target.fileno())
        Path(temporary_name).replace(sidecar)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return sidecar


def read_identity_provenance(
    data_path: Path,
    *,
    snapshot_root: Path,
    expected_snapshot_id: str | None = None,
    row_id_column: str | None = None,
) -> DatasetIdentityProvenance:
    """Проверить sidecar, parquet bytes, row keys и полный immutable snapshot."""
    data_path = Path(data_path)
    sidecar = identity_sidecar_path(data_path)
    if not data_path.is_file() or not sidecar.is_file() or sidecar.is_symlink():
        raise ValueError("Enabled identity mode требует parquet и его provenance sidecar")
    if sidecar.stat().st_size > MAX_SIDECAR_BYTES:
        raise ValueError("Identity sidecar превышает допустимый размер")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Identity sidecar не является корректным JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Identity sidecar имеет неверную форму")
    checksum = payload.pop("provenance_sha256", None)
    if checksum != hashlib.sha256(_canonical_json(payload)).hexdigest():
        raise ValueError("Identity sidecar checksum не совпадает")
    payload["provenance_sha256"] = checksum
    if (
        payload.get("format") != "sports-forecast-dataset-identity"
        or payload.get("version") != DATA_PROVENANCE_VERSION
    ):
        raise ValueError("Identity sidecar имеет неподдерживаемый format/version")
    if any(
        not isinstance(payload.get(field), str)
        or not payload[field].strip()
        or len(payload[field]) > limit
        for field, limit in (("adapter_name", 128), ("source", 128), ("tournament", 500))
    ):
        raise ValueError("Identity sidecar содержит некорректные adapter/source/tournament")
    if (
        payload.get("parquet_sha256") != _sha256_file(data_path)
        or payload.get("parquet_bytes") != data_path.stat().st_size
    ):
        raise ValueError("Parquet hash/size изменился после записи identity sidecar")
    if expected_snapshot_id is not None and payload.get("snapshot_id") != expected_snapshot_id:
        raise ValueError("Identity sidecar относится к другому registry snapshot")
    configured_row_column = row_id_column or payload.get("row_id_column")
    allow_duplicates = payload.get("allow_duplicate_row_ids") is True
    actual_row_ids = _row_ids(
        data_path, str(configured_row_column), allow_duplicates=allow_duplicates
    )
    if payload.get("dataset_row_count") != len(actual_row_ids):
        raise ValueError("Число строк parquet не соответствует sidecar")
    raw_resolutions = payload.get("resolutions")
    if not isinstance(raw_resolutions, list) or len(raw_resolutions) > MAX_SIDECAR_RESOLUTIONS:
        raise ValueError("Identity sidecar содержит слишком много resolutions")
    resolutions: list[IdentityRowResolution] = []
    for result in raw_resolutions:
        if not isinstance(result, dict):
            raise ValueError("Identity sidecar содержит некорректный resolution")
        if set(result) != {"row_id", "source_event_id", "status", "project_event_id", "reason"}:
            raise ValueError("Identity sidecar resolution содержит неизвестные поля")
        row_id = result["row_id"]
        source_event_id = result["source_event_id"]
        reason = result["reason"]
        status = result["status"]
        project_event_id = result["project_event_id"]
        if (
            not isinstance(row_id, str)
            or not row_id.strip()
            or len(row_id) > 500
            or not isinstance(source_event_id, str)
            or len(source_event_id) > 500
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 500
            or status not in {"resolved", "unresolved", "ambiguous", "conflict"}
        ):
            raise ValueError("Identity sidecar resolution содержит некорректные значения")
        if status == "resolved":
            if not isinstance(project_event_id, str):
                raise ValueError("Resolved sidecar row должен содержать project event UUID")
            try:
                UUID(project_event_id)
            except ValueError as exc:
                raise ValueError("Resolved sidecar row содержит некорректный UUID") from exc
        elif project_event_id is not None:
            raise ValueError("Неразрешённый sidecar row не может содержать project event UUID")
        resolutions.append(
            IdentityRowResolution(row_id, source_event_id, status, project_event_id, reason)
        )
    if set(actual_row_ids) != {str(result.row_id) for result in resolutions}:
        raise ValueError("Identity sidecar содержит отсутствующие или лишние row IDs")
    digest = payload.get("snapshot_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or payload.get("snapshot_id") != f"ir1:{digest}"
    ):
        raise ValueError("Identity sidecar содержит некорректный snapshot digest")
    snapshot = verify_registry_snapshot(Path(snapshot_root) / digest)
    if snapshot.snapshot_id != payload.get("snapshot_id"):
        raise ValueError("Identity sidecar snapshot ID не совпадает с verified manifest")
    event_ids = {str(event.id) for event in snapshot.event_snapshot.events}
    if any(
        result.project_event_id not in event_ids
        for result in resolutions
        if result.status == "resolved"
    ):
        raise ValueError("Resolved project event отсутствует в verified registry snapshot")
    if len({result.row_id for result in resolutions}) != len(resolutions):
        raise ValueError("Identity sidecar содержит повторные resolution row IDs")
    return DatasetIdentityProvenance(
        str(payload["snapshot_id"]),
        digest,
        str(payload["parquet_sha256"]),
        int(payload["dataset_row_count"]),
        str(payload["adapter_name"]),
        str(payload["source"]),
        str(payload["tournament"]),
        tuple(resolutions),
        snapshot,
    )


def propagate_identity_provenance(
    source_path: Path,
    target_path: Path,
    *,
    snapshot_root: Path,
    row_id_column: str,
    expected_snapshot_id: str | None = None,
    allow_duplicate_row_ids: bool = False,
) -> Path:
    """Перенести mapping по строкам после clean/features с проверкой обеих таблиц."""
    source = read_identity_provenance(
        source_path,
        snapshot_root=snapshot_root,
        expected_snapshot_id=expected_snapshot_id,
    )
    output_row_ids = _row_ids(
        Path(target_path), row_id_column, allow_duplicates=allow_duplicate_row_ids
    )
    source_results = {str(item.row_id): item for item in source.resolutions}
    if not set(output_row_ids) <= set(source_results):
        raise ValueError("Clean/features создали или изменили provider row ID")
    selected = tuple(source_results[row_id] for row_id in sorted(set(output_row_ids)))
    return write_identity_provenance(
        Path(target_path),
        snapshot=source.snapshot,
        adapter_name=source.adapter_name,
        source=source.source,
        tournament=source.tournament,
        resolutions=selected,
        row_id_column=row_id_column,
        allow_duplicate_row_ids=allow_duplicate_row_ids,
    )
