"""Read-only контракты provenance для legacy model artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class LegacyManifestError(ValueError):
    """Legacy manifest не позволяет безопасно загрузить прежний артефакт."""


@dataclass(frozen=True)
class LegacyModelManifest:
    """Воспроизводимая ссылка на прежний NHL-артефакт без переобучения."""

    model_identity: str
    artifact_path: Path
    code_ref: str
    data_ref: str
    config_ref: str
    metrics_ref: str


def load_legacy_manifest(manifest_path: Path, project_root: Path) -> LegacyModelManifest:
    """Прочитать и проверить legacy manifest, не меняя артефакты или pointer."""
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LegacyManifestError(f"Legacy manifest недоступен: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise LegacyManifestError("Legacy manifest должен быть YAML-объектом")

    fields = ("model_identity", "artifact_ref", "code_ref", "data_ref", "config_ref", "metrics_ref")
    values: dict[str, str] = {}
    for field in fields:
        value: Any = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise LegacyManifestError(f"Legacy manifest: {field} обязателен")
        values[field] = value.strip()
    if not values["model_identity"].startswith("legacy:nhl:"):
        raise LegacyManifestError("Legacy manifest поддерживает только NHL identity")
    artifact_ref = Path(values["artifact_ref"])
    if artifact_ref.is_absolute() or ".." in artifact_ref.parts:
        raise LegacyManifestError("Legacy manifest содержит небезопасный путь артефакта")
    artifact_path = project_root / artifact_ref
    if not artifact_path.is_dir():
        raise LegacyManifestError(f"Legacy артефакт не найден: {artifact_path}")
    return LegacyModelManifest(
        model_identity=values["model_identity"],
        artifact_path=artifact_path,
        code_ref=values["code_ref"],
        data_ref=values["data_ref"],
        config_ref=values["config_ref"],
        metrics_ref=values["metrics_ref"],
    )
