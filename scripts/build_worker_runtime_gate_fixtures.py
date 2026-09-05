"""Собрать минимальные immutable bundles для Worker image release gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from sports_forecast.deploy.canonical_bootstrap import build_nhl_bootstrap_bundle
from sports_forecast.deploy.model_bundle import build_model_bundle, install_model_bundle
from sports_forecast.deploy.source_state import build_nhl_source_state_bundle


def _make_readable_for_runtime(bundle_path: Path) -> None:
    """Разрешить непривилегированному Worker только чтение test fixture."""
    for path in bundle_path.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    bundle_path.chmod(0o755)


def build_fixtures(output_root: Path, *, app_version: str) -> tuple[Path, Path, Path]:
    """Создать runtime fixtures штатными builders и installers.

    Args:
        output_root: Временный каталог, передаваемый Docker через bind mount.

    Returns:
        Пути source-state, canonical bootstrap и runtime model root.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    # Fixture не содержит секретов; final Worker запускается как UID 10001 и
    # должен пройти read-only bind-mount также при root, созданном через mktemp.
    output_root.chmod(0o755)
    source_dir = output_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_csv = source_dir / "source.csv"
    source_csv.write_text(
        "id,datetime,match_is_end,home_score_ft,away_score_ft,match_end,home_team,away_team\n"
        "fixture-1,2026-09-01T12:00:00Z,1,3,2,REG,Home,Away\n",
        encoding="utf-8",
    )
    odds_path = source_dir / "odds" / "pinnacle_odds.parquet"
    odds_path.parent.mkdir()
    pd.DataFrame(
        [{"game_date": "2026-09-01", "pinnacle_winner_withOT_home_close": 2.1}]
    ).to_parquet(odds_path)
    checkpoint = source_dir / "odds" / "refresh_state.json"
    checkpoint.write_text(json.dumps({"last_successful_date": "2026-09-01"}), encoding="utf-8")

    source_state = build_nhl_source_state_bundle(
        source_csv, odds_path, checkpoint, output_root / "source-state"
    )
    canonical_bootstrap = build_nhl_bootstrap_bundle(
        source_csv, output_root / "canonical-bootstrap"
    )
    model_source = output_root / "model-source"
    model_source.mkdir()
    (model_source / "fixture-model.bin").write_bytes(b"fixture-model-v1")
    runtime_models = output_root / "runtime_models"
    model_bundle = build_model_bundle(
        model_source,
        runtime_models / "bundles",
        model_identity="fixture-model",
        app_version=app_version,
        source_commit="fixture-commit",
        release=f"v{app_version}",
    )
    install_model_bundle(model_bundle.path, runtime_models, app_version=app_version)
    _make_readable_for_runtime(source_state.path)
    _make_readable_for_runtime(canonical_bootstrap.path)
    _make_readable_for_runtime(runtime_models)
    return source_state.path, canonical_bootstrap.path, runtime_models


def main() -> None:
    """Создать fixtures и вывести shell-совместимые пути без чувствительных данных."""
    parser = argparse.ArgumentParser(description="Fixtures для Worker runtime release gate")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    args = parser.parse_args()
    source_state, canonical_bootstrap, runtime_models = build_fixtures(
        args.output_root, app_version=args.app_version
    )
    print(f"source_state={source_state}")  # noqa: T201
    print(f"canonical_bootstrap={canonical_bootstrap}")  # noqa: T201
    print(f"runtime_models={runtime_models}")  # noqa: T201


if __name__ == "__main__":
    main()
