"""Контракт read-only manifest для legacy NHL-артефакта."""

from __future__ import annotations

from pathlib import Path

import pytest

from sports_forecast.deploy.model_registry import LegacyManifestError, load_legacy_manifest


def test_legacy_manifest_loads_existing_artifact_metadata_without_training(tmp_path: Path) -> None:
    """Legacy manifest возвращает путь и provenance прежней NHL-модели."""
    artifact = tmp_path / "models" / "nhl" / "winner_withOT" / "best"
    artifact.mkdir(parents=True)
    manifest_path = tmp_path / "legacy-nhl.yaml"
    manifest_path.write_text(
        "model_identity: legacy:nhl:winner_withOT:2025-01-01\n"
        "artifact_ref: models/nhl/winner_withOT/best\n"
        "code_ref: git:abc123\n"
        "data_ref: dvc:def456\n"
        "config_ref: conf/tournament/nhl.yaml\n"
        "metrics_ref: mlflow:run-123\n",
        encoding="utf-8",
    )

    manifest = load_legacy_manifest(manifest_path, tmp_path)

    assert manifest.model_identity == "legacy:nhl:winner_withOT:2025-01-01"
    assert manifest.artifact_path == artifact


def test_legacy_manifest_rejects_missing_artifact(tmp_path: Path) -> None:
    """Manifest не подменяет отсутствующий legacy artifact переобучением."""
    manifest_path = tmp_path / "legacy-nhl.yaml"
    manifest_path.write_text(
        "model_identity: legacy:nhl:winner_withOT:2025-01-01\n"
        "artifact_ref: models/nhl/winner_withOT/best\n"
        "code_ref: git:abc123\n"
        "data_ref: dvc:def456\n"
        "config_ref: conf/tournament/nhl.yaml\n"
        "metrics_ref: mlflow:run-123\n",
        encoding="utf-8",
    )

    with pytest.raises(LegacyManifestError, match="артефакт"):
        load_legacy_manifest(manifest_path, tmp_path)
