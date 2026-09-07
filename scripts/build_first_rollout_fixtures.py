"""Создать минимальные production-like fixtures для isolated first-rollout."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from catboost import CatBoostClassifier

from sports_forecast.config.loaders import load_tournament_config
from sports_forecast.deploy.canonical_bootstrap import build_nhl_bootstrap_bundle
from sports_forecast.deploy.model_bundle import build_model_bundle, install_model_bundle
from sports_forecast.deploy.source_state import build_nhl_source_state_bundle


def _source_rows() -> list[dict[str, object]]:
    """Сформировать 11 finished и одно upcoming NHL event из tournament contract."""
    tournament = load_tournament_config("nhl")
    columns = set(tournament.data_clean.select_columns)
    columns -= {
        "status",
        *dict(tournament.data_clean.column_mapping).values(),
        *tournament.data_clean.derived_columns.keys(),
    }
    columns.update(
        {
            "id",
            "datetime",
            "match_is_end",
            "home_score_ft",
            "away_score_ft",
            "match_end",
            "home_team",
            "away_team",
        }
    )
    rows: list[dict[str, object]] = []
    for index in range(12):
        finished = index < 11
        row: dict[str, object] = dict.fromkeys(columns, 0)
        row.update(
            {
                "id": f"fixture-{index}",
                "datetime": f"2024-01-{index + 1:02d}T20:00:00Z"
                if finished
                else "2027-01-01T20:00:00Z",
                "match_is_end": int(finished),
                "home_score_ft": 3 if finished else None,
                "away_score_ft": 2 if finished else None,
                "match_end": "REG" if finished else None,
                "home_team": f"H{index % 3}",
                "away_team": f"A{index % 3}",
                "season": "20232024",
                "game_type": "R",
            }
        )
        rows.append(row)
    return rows


def build_fixtures(root: Path, *, app_version: str) -> dict[str, Path]:
    """Собрать immutable fixtures без сети и developer datasets."""
    root.mkdir(parents=True, exist_ok=True)
    source_root = root / "source" / "nhl"
    source_root.mkdir(parents=True, exist_ok=True)
    source_csv = source_root / "current.csv"
    pd.DataFrame(_source_rows()).to_csv(source_csv, index=False)
    odds = source_root / "odds" / "pinnacle_odds.parquet"
    odds.parent.mkdir(exist_ok=True)
    pd.DataFrame(
        [{"game_date": "2024-01-01", "pinnacle_winner_withOT_home_close": 2.0}]
    ).to_parquet(odds)
    checkpoint = odds.parent / "refresh_state.json"
    checkpoint.write_text('{"last_successful_date":"2024-01-01"}', encoding="utf-8")
    source_state = build_nhl_source_state_bundle(
        source_csv, odds, checkpoint, root / "source-state"
    )
    bootstrap = build_nhl_bootstrap_bundle(source_csv, root / "bootstrap")
    model_source = root / "model-source"
    model_source.mkdir(exist_ok=True)
    model = CatBoostClassifier(iterations=2, depth=2, verbose=False, random_seed=1)
    model.fit(pd.DataFrame({"weekday": [1, 2, 3, 4]}), [0, 1, 0, 1])
    model.save_model(str(model_source / "fixture_prod.cbm"))
    (model_source / "features.txt").write_text("weekday\n", encoding="utf-8")
    (model_source / "deploy.yaml").write_text(
        "model:\n  algorithm: catboost_reg\n  featureset: advanced\n", encoding="utf-8"
    )
    runtime_models = root / "runtime_models"
    first_bundle = build_model_bundle(
        model_source,
        runtime_models / "bundles",
        model_identity="first-rollout-fixture-previous",
        app_version=app_version,
        source_commit="fixture",
        release=f"v{app_version}",
    )
    second_bundle = build_model_bundle(
        model_source,
        runtime_models / "bundles",
        model_identity="first-rollout-fixture-current",
        app_version=app_version,
        source_commit="fixture",
        release=f"v{app_version}",
    )
    install_model_bundle(first_bundle.path, runtime_models, app_version=app_version)
    install_model_bundle(second_bundle.path, runtime_models, app_version=app_version)
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return {
        "source": source_csv,
        "source_state": source_state.path,
        "bootstrap": bootstrap.path,
        "runtime_models": runtime_models,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fixtures production first-rollout")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    args = parser.parse_args()
    for name, path in build_fixtures(args.root, app_version=args.app_version).items():
        print(f"{name}={path}")  # noqa: T201


if __name__ == "__main__":
    main()
