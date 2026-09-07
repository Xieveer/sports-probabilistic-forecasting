"""Runtime entrypoint archive-sync с безопасным выбором immutable artifact."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from sports_forecast.deploy.archive_sync import (
    ArchiveSyncError,
    Boto3ObjectStorage,
    sync_operational_archive,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_ARTIFACT = re.compile(r"^sha256:[0-9a-f]{64}$")


def select_artifact(archive_root: Path) -> Path:
    """Выбрать единственный top-level verified candidate без mutable pointer."""
    root = archive_root / "operational-archive"
    candidates = (
        sorted(
            item
            for item in root.iterdir()
            if item.is_dir()
            and _ARTIFACT.fullmatch(item.name)
            and (item / "manifest.json").is_file()
        )
        if root.is_dir()
        else []
    )
    if len(candidates) != 1:
        raise ArchiveSyncError("Для archive-sync ожидается ровно один top-level immutable artifact")
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    """Синхронизировать единственный archive artifact из controlled bind mount."""
    parser = argparse.ArgumentParser(description="Runtime sync immutable operational archive")
    parser.add_argument("--archive-root", type=Path, default=Path("/app/archive"))
    parser.add_argument("--state-root", type=Path, default=Path("/app/sync-state"))
    parser.add_argument(
        "--prefix", default=os.getenv("SF_OPERATIONAL_ARCHIVE_PREFIX", "operational-archive")
    )
    args = parser.parse_args(argv)
    try:
        result = sync_operational_archive(
            select_artifact(args.archive_root),
            args.state_root,
            Boto3ObjectStorage.from_environment(),
            prefix=args.prefix,
        )
        logger.info("Archive sync завершён artifact_id=%s", result.artifact_id)
        return 0
    except (ArchiveSyncError, OSError, ValueError) as exc:
        logger.error("Archive sync не выполнен: %s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
