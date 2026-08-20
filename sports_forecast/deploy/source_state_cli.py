"""CLI initial NHL source-state build/install без provider API."""

from __future__ import annotations

import argparse
from pathlib import Path

from sports_forecast.deploy.source_state import (
    SourceStateError,
    build_nhl_source_state_bundle,
    install_nhl_source_state_bundle,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Собрать локальный bundle или verify/install его на VPS."""
    parser = argparse.ArgumentParser(description="NHL immutable source-state bundle")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-csv", required=True, type=Path)
    build.add_argument("--odds-store", required=True, type=Path)
    build.add_argument("--checkpoint", required=True, type=Path)
    build.add_argument("--bundle-root", required=True, type=Path)
    build.add_argument("--run-id", default="initial-bootstrap")
    install = commands.add_parser("install")
    install.add_argument("--bundle", required=True, type=Path)
    install.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            artifact = build_nhl_source_state_bundle(
                args.source_csv,
                args.odds_store,
                args.checkpoint,
                args.bundle_root,
                run_id=args.run_id,
            )
        else:
            artifact = install_nhl_source_state_bundle(args.bundle, args.source_root)
        print(artifact.artifact_id)  # noqa: T201 - оператору нужен только immutable ID.
    except (OSError, SourceStateError, ValueError) as exc:
        logger.error("NHL source-state не обработан: %s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
