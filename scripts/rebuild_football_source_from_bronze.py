#!/usr/bin/env python3
# ruff: noqa: E402 — ``sys.path`` до импортов ``sports_forecast`` для ``uv run python scripts/...``.
"""Пересобрать ``source.csv`` football_nationals из bronze-кэша (без API).

Usage::

    uv run python scripts/rebuild_football_source_from_bronze.py
    uv run python scripts/rebuild_football_source_from_bronze.py --verify-only
    make football-rebuild-source
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# scripts/ не в PYTHONPATH при прямом запуске файла
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.data.providers.smart_tables.assembler import rebuild_dataframe_from_bronze
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

DEFAULT_STORAGE = PROJECT_ROOT / "data" / "source" / "football_nationals"
DEFAULT_OUTPUT = DEFAULT_STORAGE / "source.csv"
DEFAULT_RAW = DEFAULT_STORAGE / "raw"
DEFAULT_RAW_PARQUET = PROJECT_ROOT / "data" / "raw" / "football_nationals" / "matches.parquet"


def _verify_source_csv(csv_path: Path, raw_parquet: Path | None) -> dict[str, float | int]:
    """Сводка качества пересобранного ``source.csv``."""
    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    n = len(df)
    empty_dt = int((df["datetime"].isna() | (df["datetime"].astype(str).str.strip() == "")).sum())
    finished = int((df["match_is_end"].astype(str).str.strip() == "1").sum())
    metrics: dict[str, float | int] = {
        "rows": n,
        "datetime_not_null_pct": 100.0 * (n - empty_dt) / n if n else 0.0,
        "match_is_end_1": finished,
        "match_is_end_1_pct": 100.0 * finished / n if n else 0.0,
        "empty_datetime": empty_dt,
    }
    if raw_parquet is not None and raw_parquet.is_file():
        raw_n = len(pd.read_parquet(raw_parquet))
        metrics["raw_parquet_rows"] = raw_n
    return metrics


def _log_metrics(metrics: dict[str, float | int]) -> None:
    logger.info("Rebuild verify: rows=%s", metrics.get("rows"))
    logger.info(
        "Rebuild verify: datetime not-null=%.2f%% (empty=%s)",
        metrics.get("datetime_not_null_pct", 0.0),
        metrics.get("empty_datetime"),
    )
    logger.info(
        "Rebuild verify: match_is_end=1 → %s (%.2f%%)",
        metrics.get("match_is_end_1"),
        metrics.get("match_is_end_1_pct", 0.0),
    )
    if "raw_parquet_rows" in metrics:
        logger.info("Rebuild verify: raw parquet rows=%s", metrics["raw_parquet_rows"])


def _assert_thresholds(metrics: dict[str, float | int]) -> None:
    rows = int(metrics.get("rows", 0))
    if rows < 11_000:
        raise SystemExit(f"Expected ~11.4k rows, got {rows}")
    if float(metrics.get("datetime_not_null_pct", 0)) < 100.0:
        raise SystemExit(f"datetime not-null {metrics.get('datetime_not_null_pct'):.2f}% < 100%")
    if float(metrics.get("match_is_end_1_pct", 0)) < 99.8:
        raise SystemExit(f"match_is_end=1 {metrics.get('match_is_end_1_pct'):.2f}% < 99.8%")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=DEFAULT_STORAGE,
        help="Каталог ingest (bronze + source.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Путь к source.csv (по умолчанию storage-dir/source.csv)",
    )
    parser.add_argument(
        "--raw-cache-dir",
        default="raw",
        help="Подкаталог bronze относительно storage-dir",
    )
    parser.add_argument(
        "--raw-parquet",
        type=Path,
        default=DEFAULT_RAW_PARQUET,
        help="Путь к matches.parquet для сравнения row count",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Только проверить существующий source.csv",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Не проверять пороги после rebuild",
    )
    args = parser.parse_args(argv)

    storage_dir: Path = args.storage_dir
    output_csv = args.output or (storage_dir / "source.csv")

    if not args.verify_only:
        raw_root = storage_dir / args.raw_cache_dir
        if not raw_root.is_dir():
            logger.error("Bronze cache not found: %s", raw_root)
            return 1
        n_dirs = sum(1 for d in raw_root.iterdir() if d.is_dir() and d.name.isdigit())
        logger.info("Rebuild from bronze: %d match dirs in %s", n_dirs, raw_root)
        df = rebuild_dataframe_from_bronze(
            storage_dir,
            output_csv,
            raw_cache_dir=args.raw_cache_dir,
        )
        logger.info("Rebuild complete: %d rows → %s", len(df), output_csv)

    if not output_csv.is_file():
        logger.error("source.csv not found: %s", output_csv)
        return 1

    metrics = _verify_source_csv(output_csv, args.raw_parquet)
    _log_metrics(metrics)
    if not args.no_verify:
        _assert_thresholds(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
