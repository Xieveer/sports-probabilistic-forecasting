"""CLI локального импорта server candidates с подтверждением durable ack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sports_forecast.deploy.registry_feedback_client import Boto3CandidateFeedbackStorage
from sports_forecast.identity.feedback import (
    import_candidate_batch,
    import_pending_candidate_batches,
)
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Импортировать candidate batch или bounded очередь для installation ID."""
    parser = argparse.ArgumentParser(description="Импортировать server registry candidates")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--prefix", default="entity-registry/v1")
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--max-batches", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        storage = Boto3CandidateFeedbackStorage.from_environment()
        registry = EntityRegistry(args.registry)
        with registry._connect(write=False):
            pass
        if args.batch_id is not None:
            batch_result = import_candidate_batch(
                storage,
                registry,
                prefix=args.prefix,
                installation_id=args.installation_id,
                batch_id=args.batch_id,
            )
            output = {
                "acknowledged": batch_result.acknowledged,
                "batch_id": batch_result.batch_id,
                "imported_candidates": batch_result.imported_candidates,
                "installation_id": batch_result.installation_id,
            }
        else:
            summary = import_pending_candidate_batches(
                storage,
                registry,
                prefix=args.prefix,
                installation_id=args.installation_id,
                max_batches=args.max_batches,
            )
            output = {
                "acknowledged_batches": summary.acknowledged_batches,
                "imported_candidates": summary.imported_candidates,
                "scanned_batches": summary.scanned_batches,
            }
    except Exception as exc:
        logger.error("Candidate feedback import failed error_code=%s", type(exc).__name__)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
