"""Контракты объединения model pool и отчёта candidate без реального обучения."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.config.portfolio import load_portfolio_catalog
from sports_forecast.training.model_pool import (
    ModelPoolDatasetError,
    build_pool_dataset,
    create_candidate_report,
    write_candidate_report,
)


def _catalog():
    return load_portfolio_catalog(Path("conf/portfolio/default.yaml"))


def test_build_pool_dataset_preserves_tournament_provenance_for_two_members() -> None:
    """Совместимые datasets объединяются и каждая строка сохраняет tournament provenance."""
    catalog = _catalog()
    datasets = {
        "football_nationals": pd.DataFrame({"id": ["n-1"], "f_x": [1.0], "target": [1]}),
        "football_friendlies": pd.DataFrame({"id": ["f-1"], "f_x": [2.0], "target": [0]}),
    }

    pooled = build_pool_dataset(
        catalog,
        "football_nationals_winner",
        datasets,
        market_spec="winner",
    )

    assert pooled.model_identity.startswith("pool:football_nationals_winner:winner:")
    assert pooled.frame["tournament"].tolist() == ["football_nationals", "football_friendlies"]


def test_pool_rejects_incompatible_dataset_contract_without_artifact() -> None:
    """Разный набор колонок не объединяется и не создаёт pool identity."""
    catalog = _catalog()
    datasets = {
        "football_nationals": pd.DataFrame({"id": ["n-1"], "f_x": [1.0], "target": [1]}),
        "football_friendlies": pd.DataFrame({"id": ["f-1"], "f_y": [2.0], "target": [0]}),
    }

    with pytest.raises(ModelPoolDatasetError, match="несовместим"):
        build_pool_dataset(catalog, "football_nationals_winner", datasets, market_spec="winner")


def test_candidate_report_contains_ml_betting_simulation_and_coverage_metrics() -> None:
    """Отчёт candidate содержит все обязательные измерения без promotion."""
    report = create_candidate_report(
        model_identity="pool:football_winner:winner:abc",
        ml_metrics={"logloss": 0.61, "auc": 0.7, "brier": 0.2},
        betting_metrics={"roi": 0.05, "coverage": 0.4, "n_bets": 12},
        simulation_metrics={"roi_std": 0.08},
    )

    assert report.model_identity == "pool:football_winner:winner:abc"
    assert report.betting_metrics["n_bets"] == 12
    assert report.simulation_metrics["roi_std"] == 0.08


def test_candidate_report_is_written_with_pool_identity(tmp_path: Path) -> None:
    """Отчёт pool-run materializes без решения о promotion."""
    report = create_candidate_report(
        model_identity="pool:football_winner:winner:abc",
        ml_metrics={"logloss": 0.61, "auc": 0.7, "brier": 0.2},
        betting_metrics={"roi": 0.05, "coverage": 0.4, "n_bets": 12},
        simulation_metrics={"roi_std": 0.08},
    )

    report_path = write_candidate_report(report, tmp_path)

    assert report_path.name == "candidate-report.json"
    assert "pool:football_winner:winner:abc" in report_path.read_text(encoding="utf-8")
