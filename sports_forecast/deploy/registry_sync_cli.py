"""Отдельный server sync опубликованного registry в PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from sports_forecast.deploy.registry_publish import Boto3RegistryStorage
from sports_forecast.deploy.registry_sync import sync_current_registry
from sports_forecast.service.db.engine import get_database_url
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Скачать current publication и атомарно установить недостающую цепочку."""
    parser = argparse.ArgumentParser(description="Установить опубликованный registry snapshot")
    parser.add_argument("--download-root", type=Path, required=True)
    parser.add_argument("--prefix", default="entity-registry/v1")
    parser.add_argument("--max-chain-length", type=int, default=100)
    parser.add_argument("--max-download-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--max-duration-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    engine: Engine | None = None
    try:
        database_url = get_database_url()
        if not database_url.startswith("postgresql"):
            raise ValueError("Registry sync требует явную PostgreSQL БД")
        engine = create_engine(database_url, pool_pre_ping=True)
        storage = Boto3RegistryStorage.from_environment()
        result = sync_current_registry(
            storage,
            engine,
            prefix=args.prefix,
            download_root=args.download_root,
            max_chain_length=args.max_chain_length,
            max_download_bytes=args.max_download_bytes,
            max_duration_seconds=args.max_duration_seconds,
        )
    except Exception as exc:
        logger.error("Registry sync завершился ошибкой error_code=%s", type(exc).__name__)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    logger.info(
        "Registry sync завершён publication_sequence=%s snapshot_id=%s applied=%s",
        result.publication_sequence,
        result.snapshot_id,
        result.applied_publications,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
