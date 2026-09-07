"""Контракт runtime выбора archive-sync artifact."""

from __future__ import annotations

from pathlib import Path

import pytest

from sports_forecast.deploy.archive_sync import ArchiveSyncError
from sports_forecast.deploy.archive_sync_runtime import select_artifact


def test_select_artifact_accepts_exactly_one_top_level_immutable_bundle(tmp_path: Path) -> None:
    """Source-state nested bundles не смешиваются с serving archive."""
    bundle = tmp_path / "operational-archive" / ("sha256:" + "a" * 64)
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "operational-archive" / "nhl-source-state" / "v1" / ("sha256:" + "b" * 64)
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text("{}", encoding="utf-8")

    assert select_artifact(tmp_path) == bundle


def test_select_artifact_rejects_missing_or_ambiguous_bundle(tmp_path: Path) -> None:
    """Runtime не угадывает, какой immutable bundle отправлять."""
    with pytest.raises(ArchiveSyncError):
        select_artifact(tmp_path)
