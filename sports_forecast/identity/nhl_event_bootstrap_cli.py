"""Ручное dry-run/apply заполнение NHL events из официального schedule API."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from omegaconf import OmegaConf

from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.data.providers.nhl.schedule import fetch_schedule_day
from sports_forecast.identity.nhl_event_bootstrap import NHLBootstrapReport, bootstrap_nhl_events
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_NHL_SOURCE_CONFIG = Path("conf/source/nhl.yaml")


def _parse_anchor(value: str) -> date:
    """Разобрать календарный anchor в строгом формате YYYY-MM-DD."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ожидается дата в формате YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Ожидается дата в формате YYYY-MM-DD")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sf-nhl-event-bootstrap",
        description="Проверить или добавить NHL events из одного официального schedule anchor.",
    )
    parser.add_argument(
        "--master", required=True, type=Path, help="Локальная owner master registry"
    )
    parser.add_argument(
        "--anchor",
        required=True,
        type=_parse_anchor,
        metavar="YYYY-MM-DD",
        help="Дата начала одного семидневного окна NHL schedule",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Сохранить однозначные события и review candidates"
    )
    return parser


def _summary(report: NHLBootstrapReport, *, anchor: date) -> dict[str, object]:
    """Собрать компактную сводку без экспорта snapshot или event payloads."""
    statuses = Counter(item.status for item in report.items)
    reasons = Counter(item.reason for item in report.items)
    return {
        "anchor": anchor.isoformat(),
        "dry_run": report.dry_run,
        "items": len(report.items),
        "counts_by_status": dict(sorted(statuses.items())),
        "counts_by_reason": dict(sorted(reasons.items())),
    }


def main(argv: list[str] | None = None) -> int:
    """Загрузить одно 7-дневное расписание и вывести результат bootstrap."""
    args = _parser().parse_args(argv)
    try:
        source_config = OmegaConf.load(_NHL_SOURCE_CONFIG)
        client = NhlApiClient(source_config.provider)
        registry = EntityRegistry(args.master)
        with registry._connect(write=False):
            pass
        games = fetch_schedule_day(client, args.anchor)
        report = bootstrap_nhl_events(
            games,
            registry,
            dry_run=not args.apply,
        )
    except Exception as exc:
        logger.error("NHL event bootstrap failed error_code=%s", type(exc).__name__)
        print(f"NHL event bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(_summary(report, anchor=args.anchor), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
