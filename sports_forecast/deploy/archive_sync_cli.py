"""CLI отдельного Object Storage sync process."""

from __future__ import annotations

import argparse
from pathlib import Path

from sports_forecast.deploy.archive_sync import (
    ArchiveSyncError,
    Boto3ObjectStorage,
    pull_latest_verified_archive,
    pull_verified_archive,
    sync_operational_archive,
)
from sports_forecast.deploy.serving_data import prepare_training_input
from sports_forecast.deploy.source_state import prepare_nhl_source_state_input
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Выполнить sync либо read-only local pull без автоматического DVC."""
    parser = argparse.ArgumentParser(description="Отдельный verified Object Storage sync archive.")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("--archive", required=True, type=Path)
    sync.add_argument("--state-root", required=True, type=Path)
    sync.add_argument("--prefix", default="operational-archive")
    pull = commands.add_parser("pull-training-input")
    pull.add_argument("--artifact-id", required=True)
    pull.add_argument("--download-root", required=True, type=Path)
    pull.add_argument("--import-root", required=True, type=Path)
    pull.add_argument("--descriptor", required=True, type=Path)
    pull.add_argument("--prefix", default="operational-archive")
    latest = commands.add_parser("pull-latest-source-state")
    latest.add_argument("--download-root", required=True, type=Path)
    latest.add_argument("--import-root", required=True, type=Path)
    latest.add_argument("--descriptor", required=True, type=Path)
    latest.add_argument("--prefix", default="operational-archive/nhl-source-state/v1")
    args = parser.parse_args(argv)
    try:
        storage = Boto3ObjectStorage.from_environment()
        if args.command == "sync":
            result = sync_operational_archive(
                args.archive, args.state_root, storage, prefix=args.prefix
            )
            print(result.artifact_id)  # noqa: T201
        elif args.command == "pull-training-input":
            archive = pull_verified_archive(
                args.artifact_id, args.download_root, storage, prefix=args.prefix
            )
            print(prepare_training_input(archive, args.import_root, args.descriptor))  # noqa: T201
        else:
            archive = pull_latest_verified_archive(args.download_root, storage, prefix=args.prefix)
            print(prepare_nhl_source_state_input(archive, args.import_root, args.descriptor))  # noqa: T201
    except (ArchiveSyncError, OSError, ValueError) as exc:
        logger.error("Archive sync не выполнен: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
