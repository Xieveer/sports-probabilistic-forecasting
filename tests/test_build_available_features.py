"""Турниры DVC features выбираются по фактическому interim, без ручного списка."""

from pathlib import Path

import pytest

from sports_forecast.features.build_available import discover_feature_tournaments


def test_discovers_every_configured_interim_tournament(tmp_path: Path) -> None:
    interim_root = tmp_path / "interim"
    config_root = tmp_path / "tournament"
    for name in ("club", "nhl"):
        (interim_root / name).mkdir(parents=True)
        (interim_root / name / "matches_interim.parquet").touch()
        config_root.mkdir(exist_ok=True)
        (config_root / f"{name}.yaml").touch()
    (config_root / "unused.yaml").touch()
    assert discover_feature_tournaments(interim_root, config_root) == ("club", "nhl")


def test_rejects_interim_without_tournament_config(tmp_path: Path) -> None:
    interim_root = tmp_path / "interim"
    (interim_root / "unknown").mkdir(parents=True)
    (interim_root / "unknown" / "matches_interim.parquet").touch()
    with pytest.raises(ValueError, match="unknown"):
        discover_feature_tournaments(interim_root, tmp_path / "tournament")
