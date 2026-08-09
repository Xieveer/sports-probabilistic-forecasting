"""CLI wiring сохранённого schedule-снимка с tournament quality gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from sports_forecast.config.loaders import (
    PROJECT_ROOT,
    load_paths_config,
    load_tournament_quality_gate_config,
)
from sports_forecast.orchestration.tournament_quality_watermark import load_watermark
from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.gates import ValidationResult
from sports_forecast.validation.tournament_quality import (
    TournamentQualityGateConfig,
    load_schedule_coverage,
    load_schedule_snapshot,
    schedule_snapshot_path,
    validate_tournament_quality_gate,
)


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Проверить сохранённые source и schedule-снимки после heavy refresh."""
    parser = argparse.ArgumentParser(description="Запустить tournament quality gate.")
    parser.add_argument("--tournament", required=True)
    parser.add_argument(
        "--last-completed-at",
        help="UTC watermark последнего завершённого матча до refresh (ISO-8601).",
    )
    parser.add_argument(
        "--watermark-file",
        type=Path,
        help="Run-scoped файл watermark, созданный до source refresh.",
    )
    args = parser.parse_args(argv)
    try:
        config = load_tournament_quality_gate_config(args.tournament)
        source_dir = Path(load_paths_config().paths.source_dir)
        base_dir = PROJECT_ROOT / source_dir / args.tournament
        last_completed_at = (
            load_watermark(args.watermark_file)
            if args.watermark_file is not None
            else _parse_utc(args.last_completed_at)
        )
        result = run_tournament_quality_gate(
            source_csv_path=base_dir / "source.csv",
            config=config,
            refreshed_at=datetime.now(UTC),
            last_completed_at=last_completed_at,
        )
    except Exception:
        logger.exception("Tournament quality gate не выполнен tournament=%s", args.tournament)
        return 1
    if not result.is_valid:
        logger.error(
            "Tournament quality gate не пройден tournament=%s errors=%d",
            args.tournament,
            len(result.errors),
        )
        return 1
    return 0


def run_tournament_quality_gate(
    *,
    source_csv_path: Path,
    config: TournamentQualityGateConfig,
    refreshed_at: datetime,
    last_completed_at: datetime | None,
) -> ValidationResult:
    """Загрузить profile-driven snapshot и выполнить gate с предыдущим watermark."""
    source_rows = pd.read_csv(source_csv_path)
    schedule_rows = load_schedule_snapshot(schedule_snapshot_path(source_csv_path, config), config)
    schedule_covered_until = load_schedule_coverage(source_csv_path, config)
    return validate_tournament_quality_gate(
        source_rows=source_rows,
        schedule_rows=schedule_rows,
        config=config,
        refreshed_at=refreshed_at,
        last_completed_at=last_completed_at,
        schedule_covered_until=schedule_covered_until,
    )


def _parse_utc(raw: str | None) -> datetime | None:
    """Распарсить optional ISO-8601 watermark и привести к UTC."""
    if raw is None or not raw.strip():
        return None
    value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
