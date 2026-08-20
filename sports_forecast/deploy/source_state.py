"""Immutable NHL source/odds state bundle и безопасная установка."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from sports_forecast.data.providers.odds.store import (
    ODDS_STORE_COLUMNS_V2,
    ODDS_STORE_COLUMNS_V3,
)
from sports_forecast.deploy.serving_data import (
    ArchiveArtifact,
    archive_snapshot,
    prepare_training_input,
    verify_archive,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_SOURCE_STATE_PREFIX = "operational-archive/nhl-source-state/v1"
_SOURCE_NAME = "source.csv"
_ODDS_NAME = "odds/pinnacle_odds.parquet"
_CHECKPOINT_NAME = "odds/refresh_state.json"
_REQUIRED = (_SOURCE_NAME, _ODDS_NAME, _CHECKPOINT_NAME)


class SourceStateError(ValueError):
    """Source-state bundle не соответствует NHL production contract."""


def _validate_inputs(source_csv: Path, odds_store: Path, checkpoint: Path) -> None:
    """Проверить наличие обязательных state files до чтения и копирования."""
    for path in (source_csv, odds_store, checkpoint):
        if not path.is_file() or path.is_symlink():
            raise SourceStateError(f"Source-state файл недоступен: {path}")
    lines = source_csv.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",") if lines else []
    if not {"id", "datetime", "match_is_end"}.issubset(header):
        raise SourceStateError("source.csv не соответствует NHL source contract")
    try:
        checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceStateError("odds refresh checkpoint не является JSON") from exc
    if not isinstance(checkpoint_payload, dict):
        raise SourceStateError("odds refresh checkpoint должен быть JSON object")


def _counts(stage: Path) -> dict[str, str]:
    """Добавить безопасные record counts и версии в provenance manifest."""
    source_rows = sum(
        1
        for line in (stage / _SOURCE_NAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    odds_rows = 0
    try:
        import pandas as pd

        odds_frame = pd.read_parquet(stage / _ODDS_NAME)
        odds_rows = len(odds_frame)
    except (ImportError, OSError, ValueError) as exc:
        raise SourceStateError("OddsStore не удалось прочитать для manifest counts") from exc
    columns = set(odds_frame.columns)
    if set(ODDS_STORE_COLUMNS_V3).issubset(columns) and not (
        set(ODDS_STORE_COLUMNS_V2) - set(ODDS_STORE_COLUMNS_V3)
    ).intersection(columns):
        odds_schema_version = "3"
    elif "commence_time_utc" in columns:
        odds_schema_version = "2"
    else:
        odds_schema_version = "1"
    return {
        "kind": "nhl_source_state",
        "source_schema_version": "1",
        "odds_schema_version": odds_schema_version,
        "checkpoint_schema_version": "1",
        "source_rows": str(max(0, source_rows - 1)),
        "odds_rows": str(odds_rows),
    }


def build_nhl_source_state_bundle(
    source_csv: Path,
    odds_store: Path,
    checkpoint: Path,
    bundle_root: Path,
    *,
    run_id: str = "initial-bootstrap",
) -> ArchiveArtifact:
    """Собрать verified initial или export bundle из полного source volume.

    Args:
        source_csv: Полная NHL история с заголовком.
        odds_store: Persistent `odds/pinnacle_odds.parquet`.
        checkpoint: Persistent `odds/refresh_state.json`.
        bundle_root: Local staging root, corresponding to Object Storage layout.
        run_id: Safe refresh/bootstrap identity for provenance.
    """
    _validate_inputs(source_csv, odds_store, checkpoint)
    stage = Path(tempfile.mkdtemp(prefix="nhl-source-state-"))
    try:
        (stage / "odds").mkdir()
        shutil.copyfile(source_csv, stage / _SOURCE_NAME)
        shutil.copyfile(odds_store, stage / _ODDS_NAME)
        shutil.copyfile(checkpoint, stage / _CHECKPOINT_NAME)
        provenance = {"tournament": "nhl", "run_id": run_id, **_counts(stage)}
        return archive_snapshot(
            stage,
            bundle_root,
            directory_name=_SOURCE_STATE_PREFIX,
            provenance=provenance,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def verify_nhl_source_state_bundle(
    bundle_path: Path, *, require_path_name: bool = True
) -> ArchiveArtifact:
    """Проверить checksums, layout и manifest source-state до install/import."""
    artifact = verify_archive(bundle_path, require_path_name=require_path_name)
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    provenance = manifest.get("provenance", {})
    if provenance.get("kind") != "nhl_source_state":
        raise SourceStateError("Manifest не является NHL source-state")
    if any(not (bundle_path / relative).is_file() for relative in _REQUIRED):
        raise SourceStateError("Source-state bundle не содержит обязательные файлы")
    if not all(isinstance(provenance.get(key), str) for key in ("source_rows", "odds_rows")):
        raise SourceStateError("Manifest не содержит record counts")
    return artifact


def install_nhl_source_state_bundle(bundle_path: Path, source_root: Path) -> ArchiveArtifact:
    """Атомарно подготовить state volume и создать current.csv из checked source.

    Все проверки и копирование выполняются во временном каталоге до замены
    production-visible files. Повторный artifact не переписывает состояние.
    """
    artifact = verify_nhl_source_state_bundle(bundle_path)
    source_root.mkdir(parents=True, exist_ok=True)
    marker = source_root / ".source-state-artifact"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == artifact.artifact_id:
        return artifact
    stage = Path(tempfile.mkdtemp(prefix="nhl-source-install-", dir=source_root))
    replacements: list[Path] = []
    backups: dict[Path, Path] = {}
    try:
        shutil.copytree(bundle_path, stage, dirs_exist_ok=True, symlinks=False)
        verify_nhl_source_state_bundle(stage, require_path_name=False)
        (stage / "current.csv").write_bytes((stage / _SOURCE_NAME).read_bytes())
        for relative in (_SOURCE_NAME, "current.csv", _ODDS_NAME, _CHECKPOINT_NAME):
            destination = source_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                backup = stage / "backup" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                destination.replace(backup)
                backups[destination] = backup
            temporary = destination.with_name(f".{destination.name}.new")
            shutil.copyfile(stage / relative, temporary)
            temporary.replace(destination)
            replacements.append(destination)
        marker_tmp = stage / ".source-state-artifact.new"
        marker_tmp.write_text(artifact.artifact_id + "\n", encoding="utf-8")
        if marker.exists() or marker.is_symlink():
            marker_backup = stage / "backup" / marker.name
            marker.replace(marker_backup)
            backups[marker] = marker_backup
        marker_tmp.replace(marker)
        replacements.append(marker)
    except Exception:
        for destination in reversed(replacements):
            destination.unlink(missing_ok=True)
        for destination, backup in backups.items():
            backup.replace(destination)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    logger.info("NHL source-state установлен artifact_id=%s", artifact.artifact_id)
    return artifact


def export_nhl_source_state(
    source_csv: Path, archive_root: Path, *, run_id: str
) -> ArchiveArtifact:
    """Экспортировать текущий source volume после успешного scheduler run."""
    source_root = source_csv.parent
    return build_nhl_source_state_bundle(
        source_csv,
        source_root / _ODDS_NAME,
        source_root / _CHECKPOINT_NAME,
        archive_root,
        run_id=run_id,
    )


def prepare_nhl_source_state_input(
    archive_path: Path, import_root: Path, descriptor_path: Path
) -> Path:
    """Подготовить verified local training/validation input с OddsStore."""
    verify_nhl_source_state_bundle(archive_path)
    descriptor = prepare_training_input(archive_path, import_root, descriptor_path)
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    partitions = set(payload.get("partitions", []))
    if not {"source.csv", _ODDS_NAME, _CHECKPOINT_NAME}.issubset(partitions):
        raise SourceStateError("Local descriptor не содержит полный NHL source-state")
    return descriptor
