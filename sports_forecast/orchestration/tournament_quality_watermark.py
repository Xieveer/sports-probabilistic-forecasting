"""Run-scoped pre-refresh watermark для tournament quality gate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from sports_forecast.config.loaders import (
    PROJECT_ROOT,
    load_paths_config,
    load_tournament_quality_gate_config,
)
from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.tournament_quality import TournamentQualityGateConfig


logger = get_logger(__name__)


def save_pre_refresh_watermark(
    source_csv_path: Path,
    output_path: Path,
    config: TournamentQualityGateConfig,
) -> None:
    """Сохранить timestamp последней completed строки до source refresh."""
    watermark = _last_completed_at(source_csv_path, config)
    payload = {"last_completed_at": watermark.isoformat() if watermark is not None else None}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(output_path)
    logger.info("Сохранён pre-refresh watermark турнира %s", config.tournament)


def load_watermark(path: Path) -> datetime | None:
    """Прочитать сохранённый watermark текущего DAG run."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    value = raw.get("last_completed_at") if isinstance(raw, dict) else None
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _last_completed_at(
    source_csv_path: Path,
    config: TournamentQualityGateConfig,
) -> datetime | None:
    """Найти последний валидный completed timestamp в существующем source.csv."""
    if not source_csv_path.is_file():
        return None
    source_rows = pd.read_csv(
        source_csv_path,
        dtype=str,
        usecols=lambda name: name in {config.datetime_column, config.source_finished_column},
    )
    required = {config.datetime_column, config.source_finished_column}
    if not required <= set(source_rows.columns):
        return None
    finished = {value.strip().casefold() for value in config.source_finished_values}
    mask = (
        source_rows[config.source_finished_column]
        .fillna("")
        .map(lambda value: str(value).strip().casefold() in finished)
    )
    timestamps = pd.to_datetime(
        source_rows.loc[mask, config.datetime_column], errors="coerce", utc=True
    ).dropna()
    if timestamps.empty:
        return None
    last_timestamp = timestamps.max()
    if not isinstance(last_timestamp, pd.Timestamp):
        return None
    value = last_timestamp.to_pydatetime()
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    """Сохранить pre-refresh watermark для profile-driven heavy DAG."""
    parser = argparse.ArgumentParser(description="Сохранить watermark до source refresh.")
    parser.add_argument("--tournament", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_tournament_quality_gate_config(args.tournament)
        source_dir = Path(load_paths_config().paths.source_dir)
        save_pre_refresh_watermark(
            PROJECT_ROOT / source_dir / args.tournament / "source.csv",
            args.output,
            config,
        )
    except Exception:
        logger.exception(
            "Не удалось сохранить pre-refresh watermark tournament=%s", args.tournament
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
