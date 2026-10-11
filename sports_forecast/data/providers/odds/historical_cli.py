"""Локальный CLI импорта и запроса исторических коэффициентов."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sports_forecast.data.providers.odds.historical import (
    import_historical_cache,
    query_provider_as_of,
)
from sports_forecast.data.providers.odds.historical_coverage import build_coverage_report
from sports_forecast.identity.snapshot import RegistrySnapshotReader, verify_registry_snapshot


def main() -> int:
    """Выполнить offline-команду import или query без Odds API client."""
    parser = argparse.ArgumentParser(description="Локальная история The Odds API")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="Импортировать cache JSON в SQLite")
    importer.add_argument("--source", type=Path, required=True, help="JSON файл или каталог cache")
    importer.add_argument("--database", type=Path, required=True)
    query = commands.add_parser("query", help="Запросить последнюю цену к моменту T")
    query.add_argument("--database", type=Path, required=True)
    query.add_argument("--registry-snapshot", type=Path, required=True)
    query.add_argument("--event-id", required=True)
    query.add_argument("--at", required=True, help="UTC timestamp с timezone")
    coverage = commands.add_parser("coverage", help="Отчёт локального покрытия Pinnacle history")
    coverage.add_argument("--database", type=Path, required=True)
    coverage.add_argument("--registry-snapshot", type=Path, required=True)
    coverage.add_argument("--from", dest="start", required=True, help="Начало kickoff окна UTC")
    coverage.add_argument(
        "--to", dest="end", required=True, help="Конец kickoff окна UTC, не включается"
    )
    coverage.add_argument("--at", required=True, help="Provider-as-of момент T с timezone")
    args = parser.parse_args()
    if args.command == "import":
        if args.source.is_file():
            files = (args.source,)
        elif args.source.is_dir():
            files = tuple(sorted(args.source.glob("*.json")))
        else:
            parser.error("--source должен указывать на существующий файл или каталог")
        summary = import_historical_cache(files, args.database)
        print(json.dumps(asdict(summary), sort_keys=True))
        return 0
    snapshot = verify_registry_snapshot(args.registry_snapshot)
    reader = RegistrySnapshotReader(snapshot)
    if args.command == "coverage":
        report = build_coverage_report(
            args.database,
            reader,
            start=datetime.fromisoformat(args.start.replace("Z", "+00:00")),
            end=datetime.fromisoformat(args.end.replace("Z", "+00:00")),
            at=datetime.fromisoformat(args.at.replace("Z", "+00:00")),
        )
        print(json.dumps(report.to_dict(), sort_keys=True))
        return 0
    selection = query_provider_as_of(
        args.database,
        reader,
        project_event_id=args.event_id,
        at=datetime.fromisoformat(args.at.replace("Z", "+00:00")),
    )
    print(
        json.dumps(
            asdict(selection) if selection is not None else None, default=str, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
