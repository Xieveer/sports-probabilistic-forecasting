"""Контракты подготовки dataset и отчёта для model pool."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from sports_forecast.config.portfolio import PortfolioCatalog


class ModelPoolDatasetError(ValueError):
    """Datasets не удовлетворяют контракту одного model pool."""


@dataclass(frozen=True)
class PooledDataset:
    """Объединённый dataset с provenance и стабильной identity пула."""

    model_identity: str
    frame: pd.DataFrame


@dataclass(frozen=True)
class CandidateReport:
    """Сопоставимый отчёт кандидата без решения о promotion."""

    model_identity: str
    ml_metrics: dict[str, float]
    betting_metrics: dict[str, float]
    simulation_metrics: dict[str, float]


def build_pool_dataset(
    catalog: PortfolioCatalog,
    pool_name: str,
    datasets: Mapping[str, pd.DataFrame],
    *,
    market_spec: str,
) -> PooledDataset:
    """Проверить и объединить datasets одного model pool с provenance строк."""
    pool = catalog.model_pools.get(pool_name)
    if pool is None or market_spec not in pool.market_specs:
        raise ModelPoolDatasetError("model pool или market_spec не найдены")
    if len(datasets) < 2:
        raise ModelPoolDatasetError("Для model pool нужны datasets минимум двух турниров")

    expected_columns: tuple[str, ...] | None = None
    frames: list[pd.DataFrame] = []
    for tournament_name, frame in datasets.items():
        tournament = catalog.tournaments.get(tournament_name)
        if tournament is None or tournament.sport != pool.sport:
            raise ModelPoolDatasetError("Турнир несовместим с model pool")
        if not any(
            membership.model_pool == pool_name and market_spec in membership.market_specs
            for membership in tournament.memberships
        ):
            raise ModelPoolDatasetError("Турнир не назначен в model pool для market_spec")
        columns = tuple(frame.columns)
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise ModelPoolDatasetError("Datasets имеют несовместимый контракт колонок")
        frames.append(frame.assign(tournament=tournament_name))

    identity_input = f"{pool_name}:{market_spec}:{','.join(sorted(datasets))}".encode()
    identity = f"pool:{pool_name}:{market_spec}:{hashlib.sha256(identity_input).hexdigest()[:16]}"
    return PooledDataset(model_identity=identity, frame=pd.concat(frames, ignore_index=True))


def create_candidate_report(
    *,
    model_identity: str,
    ml_metrics: dict[str, float],
    betting_metrics: dict[str, float],
    simulation_metrics: dict[str, float],
) -> CandidateReport:
    """Создать отчёт с обязательными ML, betting, simulation и coverage метриками."""
    required = (
        (ml_metrics, {"logloss", "auc", "brier"}),
        (betting_metrics, {"roi", "coverage", "n_bets"}),
        (simulation_metrics, {"roi_std"}),
    )
    if not model_identity.startswith("pool:"):
        raise ValueError("Candidate report требует identity model pool")
    for metrics, keys in required:
        if not keys <= metrics.keys():
            raise ValueError("Candidate report не содержит обязательные метрики")
    return CandidateReport(
        model_identity, dict(ml_metrics), dict(betting_metrics), dict(simulation_metrics)
    )


def write_candidate_report(report: CandidateReport, output_dir: Path) -> Path:
    """Сохранить candidate report без изменения deployment profile или pointer."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "candidate-report.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(asdict(report), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
