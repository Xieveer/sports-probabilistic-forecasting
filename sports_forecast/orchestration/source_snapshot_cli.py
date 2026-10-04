"""CLI autonomous source acquisition перед canonical refresh."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sports_forecast.orchestration.source_snapshot import refresh_and_publish_source_snapshot
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Получить source и опубликовать current snapshot с выбранным odds режимом."""
    parser = argparse.ArgumentParser(description="Обновить scheduler source snapshot")
    parser.add_argument("--tournament", required=True, help="Идентификатор tournament source")
    parser.add_argument(
        "--odds-enabled",
        choices=("true", "false"),
        default="true",
        help="Выполнять odds post-step при сборе source",
    )
    args = parser.parse_args(argv)
    try:
        snapshot = refresh_and_publish_source_snapshot(
            args.tournament,
            Path(os.environ["SF_CANONICAL_SOURCE_SNAPSHOT"]),
            odds_enabled=args.odds_enabled == "true",
        )
    except (KeyError, OSError, ValueError) as error:
        logger.error("Source snapshot не опубликован: %s", type(error).__name__)
        return 1
    print(snapshot)  # noqa: T201 - безопасный путь нужен systemd-оператору.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
