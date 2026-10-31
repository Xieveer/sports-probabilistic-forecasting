"""Локальный DVC features stage по фактически подготовленным турнирам."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydra import compose, initialize_config_dir

from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.identity.data_provenance import load_enabled_registry_snapshot
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def discover_feature_tournaments(interim_root: Path, config_root: Path) -> tuple[str, ...]:
    """Найти все подготовленные interim-турниры и проверить их конфиги."""
    names = tuple(
        sorted(
            path.parent.name
            for path in interim_root.glob("*/matches_interim.parquet")
            if path.is_file()
        )
    )
    if not names:
        raise ValueError(f"Нет interim-турниров для features: {interim_root}")
    missing = [name for name in names if not (config_root / f"{name}.yaml").is_file()]
    if missing:
        raise ValueError(f"Нет конфигурации турниров для features: {', '.join(missing)}")
    return names


def build_available_features(project_root: Path, *, features_name: str) -> tuple[str, ...]:
    """Построить признаки для всех подготовленных турниров через Hydra-конфиг."""
    interim_root = project_root / "data/interim"
    names = discover_feature_tournaments(interim_root, project_root / "conf/tournament")
    snapshot = load_enabled_registry_snapshot(project_root)
    with initialize_config_dir(version_base="1.3", config_dir=str(project_root / "conf")):
        for name in names:
            cfg = compose(
                config_name="features_pipeline",
                overrides=[f"tournament={name}", f"features={features_name}"],
            )
            logger.info("DVC features: %s", name)
            process_tournament_new(
                name,
                project_root / cfg.paths.interim_dir,
                project_root / cfg.paths.processed_dir,
                cfg.features,
                tournament_cfg=cfg.tournament,
                identity_snapshot=snapshot,
            )
    return names


def main() -> None:
    """CLI для локального DVC features stage."""
    parser = argparse.ArgumentParser(description="Признаки для всех подготовленных турниров")
    parser.add_argument("--features", default="basic")
    args = parser.parse_args()
    build_available_features(PROJECT_ROOT, features_name=args.features)


if __name__ == "__main__":
    main()
