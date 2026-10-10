"""Один локальный цикл кандидата из проверяемого каталога портфеля."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from sports_forecast.config.loaders import load_source_config
from sports_forecast.config.portfolio import PortfolioCatalog, load_portfolio_catalog
from sports_forecast.training.candidate_report import build_tournament_candidate_report
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CandidatePlan:
    """Состав одного запуска кандидата, полученный из каталога."""

    source: str
    tournament: str
    market_spec: str
    train_overrides: tuple[str, ...]
    features: str


def build_candidate_plan(catalog: PortfolioCatalog, profile_name: str) -> CandidatePlan:
    """Проверить профиль и построить параметры существующего общего pipeline."""
    profile = catalog.deployment_profiles.get(profile_name)
    if profile is None or profile.state != "candidate":
        raise ValueError(f"Профиль {profile_name} не найден или не является кандидатом")
    algorithm = profile.candidate_algorithm
    features = profile.candidate_features
    bookmaker = profile.candidate_bookmaker
    if not algorithm or not features or not bookmaker:
        raise ValueError(f"Профиль {profile_name} не задаёт параметры обучения кандидата")
    if profile.market_spec != "winner":
        raise ValueError("Локальный candidate-цикл поддерживает только winner long-format")
    tournament = catalog.tournaments[profile.tournament]
    return CandidatePlan(
        source=tournament.source,
        tournament=tournament.name,
        market_spec=profile.market_spec,
        train_overrides=(
            f"tournament={tournament.name}",
            "market=winner",
            f"market_spec={profile.market_spec}",
            f"algorithm={algorithm}",
            f"features={features}",
            f"bookmaker={bookmaker}",
        ),
        features=features,
    )


def _run_stage(
    root: Path, module: str, args: tuple[str, ...], *, source_filter: str | None = None
) -> None:
    env = os.environ.copy()
    if source_filter:
        env["SF_TOURNAMENT_FILTER"] = source_filter
    else:
        env.pop("SF_TOURNAMENT_FILTER", None)
    logger.info("Кандидат: запуск %s %s", module, " ".join(args))
    subprocess.run((sys.executable, "-m", module, *args), cwd=root, env=env, check=True)


def _tracking_uri(root: Path) -> str:
    raw = yaml.safe_load((root / "conf/mlflow/mlflow.yaml").read_text(encoding="utf-8"))
    uri = str(raw["tracking_uri"])
    if uri.startswith("sqlite:///") and not uri.startswith("sqlite:////"):
        return f"sqlite:///{(root / uri.removeprefix('sqlite:///')).resolve()}"
    return uri


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_candidate(root: Path, catalog_path: Path, profile_name: str, output_dir: Path) -> Path:
    """Выполнить ingest→clean→features→train→report без promotion и scheduler."""
    import mlflow

    catalog = load_portfolio_catalog(catalog_path)
    plan = build_candidate_plan(catalog, profile_name)
    source_config = load_source_config(plan.source)
    provider = source_config.get("provider")
    if provider is None or provider.get("type") != "file":
        raise ValueError("Локальный candidate-цикл требует файловый источник без сетевого сбора")
    source_path = root / "data/source" / plan.source / "source.csv"
    if not source_path.is_file():
        raise ValueError(f"Локальный CSV кандидата не найден: {source_path}")

    raw_path = root / "data/raw" / plan.tournament / "matches.parquet"
    interim_path = root / "data/interim" / plan.tournament / "matches_interim.parquet"
    processed_path = root / "data/processed" / plan.tournament / "train_long.parquet"
    started_ms = int(time.time() * 1000)
    for module, args, source_filter, expected in (
        ("sports_forecast.data.ingest", (), plan.source, raw_path),
        ("sports_forecast.data.clean", (), plan.tournament, interim_path),
        (
            "sports_forecast.features.features_build",
            (f"tournament={plan.tournament}", f"features={plan.features}"),
            None,
            processed_path,
        ),
    ):
        old_mtime = expected.stat().st_mtime_ns if expected.exists() else None
        _run_stage(root, module, args, source_filter=source_filter)
        if not expected.is_file() or expected.stat().st_mtime_ns == old_mtime:
            raise ValueError(f"Этап {module} не обновил ожидаемый файл {expected}")

    raw = pd.read_parquet(raw_path, columns=["competition_code"])
    if raw["competition_code"].isna().any():
        raise ValueError("В данных кандидата отсутствует код соревнования")
    codes = set(raw["competition_code"].dropna().astype(str))
    processed_sha256 = _sha256(processed_path)
    _run_stage(root, "sports_forecast.train", plan.train_overrides)
    if _sha256(processed_path) != processed_sha256:
        raise ValueError("Данные кандидата изменились во время обучения")

    client = mlflow.tracking.MlflowClient(tracking_uri=_tracking_uri(root))
    experiments = client.search_experiments()
    runs = client.search_runs([item.experiment_id for item in experiments], max_results=100)
    matched = [
        run
        for run in runs
        if run.info.start_time >= started_ms
        and run.data.tags.get("tournament") == plan.tournament
        and run.data.tags.get("market_spec") == plan.market_spec
        and run.data.tags.get("algorithm")
        == catalog.deployment_profiles[profile_name].candidate_algorithm
    ]
    if len(matched) != 1:
        raise ValueError(f"Ожидался один новый MLflow run кандидата, найдено {len(matched)}")
    run = matched[0]

    with tempfile.TemporaryDirectory(prefix="candidate-report-") as temp_dir:
        trace_path = Path(
            client.download_artifacts(run.info.run_id, "test_bet_trace.csv", dst_path=temp_dir)
        )
        report = build_tournament_candidate_report(
            catalog,
            profile_name,
            run_id=run.info.run_id,
            run_status=run.info.status,
            tags=run.data.tags,
            metrics=run.data.metrics,
            bet_trace=pd.read_csv(trace_path),
            competition_codes=codes,
            data_sha256=processed_sha256,
            data_rows=len(raw),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{plan.tournament}-{plan.market_spec}-{run.info.run_id[:12]}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    logger.info("Отчёт кандидата: %s", path)
    return path


def main() -> int:
    """CLI локального candidate-цикла по имени deployment profile."""
    parser = argparse.ArgumentParser(description="Собрать кандидата из каталога портфеля")
    parser.add_argument("profile", help="Имя candidate deployment profile")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/changes/candidates"))
    args = parser.parse_args()
    try:
        run_candidate(
            PROJECT_ROOT,
            PROJECT_ROOT / "conf/portfolio/default.yaml",
            args.profile,
            args.output_dir,
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        logger.error("Кандидат не готов: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
