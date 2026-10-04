"""Ограниченная server-side публикация candidate outbox и сбор подтверждений."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from sports_forecast.deploy.registry_publish import (
    Boto3RegistryStorage,
    RegistryStorageError,
    _credential_from_environment,
)
from sports_forecast.service.db.registry_feedback import (
    RegistryCandidateFeedback,
    installation_id_from_environment,
)
from sports_forecast.utils.log_config import get_logger


_DEFAULT_PREFIX = "entity-registry/v1"
_MAX_BATCHES = 100
_MAX_ROWS = 100
_MAX_BYTES = 1024 * 1024
logger = get_logger(__name__)


class RegistryFeedbackCliError(RuntimeError):
    """Небезопасная или неполная CLI configuration."""


def _database_url_from_environment() -> str:
    """Получить PostgreSQL URL только из явно заданного secret file."""
    file_path = os.environ.get("DATABASE_URL_FILE", "").strip()
    if not file_path:
        raise RegistryFeedbackCliError("DATABASE_URL_FILE обязателен для server feedback publisher")
    try:
        raw_url = Path(file_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RegistryFeedbackCliError("DATABASE_URL_FILE недоступен") from exc
    if not raw_url or len(raw_url) > 16_384:
        raise RegistryFeedbackCliError("DATABASE_URL_FILE пуст или превышает 16 KiB")
    try:
        backend = make_url(raw_url).get_backend_name()
    except Exception as exc:
        raise RegistryFeedbackCliError("DATABASE_URL_FILE содержит некорректный URL") from exc
    if backend != "postgresql":
        raise RegistryFeedbackCliError("Feedback publisher требует PostgreSQL DATABASE_URL_FILE")
    return raw_url


def _feedback_storage_from_environment() -> Boto3RegistryStorage:
    """Создать Object Storage transport с отдельной server feedback identity."""
    endpoint = os.environ.get("SF_OBJECT_STORAGE_ENDPOINT", "")
    bucket = os.environ.get("SF_OBJECT_STORAGE_BUCKET", "")
    access_key_id = _credential_from_environment("SF_REGISTRY_FEEDBACK_SERVER_ACCESS_KEY_ID")
    secret_access_key = _credential_from_environment(
        "SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY"
    )
    if not endpoint or not bucket or not access_key_id or not secret_access_key:
        raise RegistryStorageError(
            "Не заданы endpoint/bucket или отдельные server feedback credentials"
        )
    return Boto3RegistryStorage(
        endpoint=endpoint,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=os.environ.get("SF_OBJECT_STORAGE_REGION", "ru-central1"),
    )


def _bounded_int(*, label: str, maximum: int):
    def parse(value: str) -> int:
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} должен быть целым числом") from exc
        if not 1 <= result <= maximum:
            raise argparse.ArgumentTypeError(f"{label} должен быть от 1 до {maximum}")
        return result

    return parse


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sf-registry-feedback-publish")
    subcommands = parser.add_subparsers(dest="command", required=True)
    publish = subcommands.add_parser("publish", help="Опубликовать bounded candidate batches")
    publish.add_argument("--prefix", default=_DEFAULT_PREFIX)
    publish.add_argument(
        "--max-batches", type=_bounded_int(label="max-batches", maximum=_MAX_BATCHES), default=10
    )
    publish.add_argument(
        "--max-rows", type=_bounded_int(label="max-rows", maximum=_MAX_ROWS), default=_MAX_ROWS
    )
    publish.add_argument(
        "--max-bytes", type=_bounded_int(label="max-bytes", maximum=_MAX_BYTES), default=_MAX_BYTES
    )
    collect = subcommands.add_parser("collect-acks", help="Собрать bounded число локальных ack")
    collect.add_argument("--prefix", default=_DEFAULT_PREFIX)
    collect.add_argument(
        "--max-batches",
        type=_bounded_int(label="max-batches", maximum=_MAX_BATCHES),
        default=_MAX_BATCHES,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Выполнить ограниченную публикацию batch-ей либо сбор их ack."""
    args = _parser().parse_args(argv)
    engine = None
    try:
        database_url = _database_url_from_environment()
        installation_id = installation_id_from_environment()
        storage = _feedback_storage_from_environment()
        engine = create_engine(database_url, pool_pre_ping=True)
        with Session(engine) as session:
            feedback = RegistryCandidateFeedback(
                session,
                storage,
                prefix=args.prefix,
                installation_id=installation_id,
                max_rows=getattr(args, "max_rows", _MAX_ROWS),
                max_bytes=getattr(args, "max_bytes", _MAX_BYTES),
            )
            if args.command == "publish":
                batch_ids: list[str] = []
                for _ in range(args.max_batches):
                    batch_id = feedback.publish_next_batch()
                    if batch_id is None:
                        break
                    batch_ids.append(batch_id)
                output: dict[str, Any] = {
                    "batch_ids": batch_ids,
                    "published_batches": len(batch_ids),
                    "status": "ok",
                }
            else:
                acknowledged = feedback.collect_acknowledgements(max_batches=args.max_batches)
                output = {
                    "acknowledged_batches": acknowledged,
                    "status": "ok",
                }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Exception messages may include SQL URLs or transport details; emit only class name.
        logger.error("Registry feedback publisher failed error_code=%s", type(exc).__name__)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
