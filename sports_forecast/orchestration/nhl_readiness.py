"""Безопасная подготовка и проверка NHL-контура перед production run."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sports_forecast.data.providers.odds.refresh import run_odds_refresh
from sports_forecast.orchestration.source_refresh import refresh_source
from sports_forecast.orchestration.tournament_quality_gate_cli import main as quality_gate_main


_READINESS_STEPS = ["source_refresh", "quality_gate", "odds_refresh", "materialize"]


def build_dry_run_plan() -> dict[str, Any]:
    """Вернуть публичный план readiness без чтения секретов и сетевых вызовов."""
    return {"mode": "dry_run", "tournament": "nhl", "steps": _READINESS_STEPS}


def has_upcoming_schedule(source_csv: Path, *, now: datetime | None = None) -> bool:
    """Проверить наличие незавершённого будущего матча в локальном NHL source."""
    frame = pd.read_csv(source_csv, usecols=["datetime", "match_is_end"])
    timestamps = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
    reference = now or datetime.now(UTC)
    unfinished = pd.to_numeric(frame["match_is_end"], errors="coerce").fillna(0).eq(0)
    return bool((unfinished & timestamps.gt(reference)).any())


def main(argv: list[str] | None = None) -> int:
    """Запустить безопасный dry-run NHL readiness."""
    parser = argparse.ArgumentParser(description="Проверка готовности NHL к production")
    parser.add_argument("--dry-run", action="store_true", help="Вывести план без внешних вызовов")
    parser.add_argument("--execute", action="store_true", help="Выполнить ограниченный NHL refresh")
    parser.add_argument(
        "--max-odds-days",
        type=int,
        default=1,
        help="Не более стольких календарных дней historical odds за один запуск (по умолчанию: 1)",
    )
    args = parser.parse_args(argv)
    if args.dry_run == args.execute:
        parser.error("укажите ровно один из --dry-run или --execute")
    if args.dry_run:
        print(json.dumps(build_dry_run_plan(), ensure_ascii=False))
        return 0
    if args.max_odds_days < 1:
        parser.error("--max-odds-days должен быть не меньше 1")
    try:
        source_csv = refresh_source("nhl", skip_odds=True)
        if not has_upcoming_schedule(source_csv):
            print(json.dumps({"status": "no_upcoming_schedule"}, ensure_ascii=False))
            return 0
        if quality_gate_main(["--tournament", "nhl"]) != 0:
            print(json.dumps({"status": "quality_gate_failed"}, ensure_ascii=False))
            return 1
        odds = run_odds_refresh(tournament="nhl", max_days_per_refresh=args.max_odds_days)
    except Exception as error:
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__}, ensure_ascii=False)
        )
        return 1
    print(
        json.dumps(
            {
                "status": "ready_without_materialization",
                "source_csv": str(source_csv),
                "odds_new_rows": odds.new_odds_rows,
                "odds_requests_remaining": odds.requests_remaining,
                "odds_days": args.max_odds_days,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
