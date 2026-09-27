"""Безопасное управление durable lifecycle одного Data Cycle из bounded job."""

from __future__ import annotations

import argparse
import json
import os
import sys

from sports_forecast.orchestration.data_cycle import (
    claim_executor,
    create_run,
    fail_run,
    finish_run,
    finish_stage,
    get_executor_owner,
    heartbeat_executor,
    recover_executor,
    start_stage,
)
from sports_forecast.orchestration.data_cycle_recovery import HostStopEvidence
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Применить одно допустимое lifecycle действие без вывода exception details."""
    parser = argparse.ArgumentParser(description="Data Cycle lifecycle control")
    commands = parser.add_subparsers(dest="action", required=True)

    create = commands.add_parser("create")
    create.add_argument("--run-id", required=True)
    create.add_argument("--tournament", required=True)
    create.add_argument("--reason", choices=("scheduled", "manual", "retry"), default="scheduled")

    claim = commands.add_parser("claim")
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--owner-id", required=True)

    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--run-id", required=True)

    owner_info = commands.add_parser("owner-info")
    owner_info.add_argument("--run-id", required=True)

    recover = commands.add_parser("recover")
    recover.add_argument("--run-id", required=True)
    recover.add_argument("--evidence", required=True)

    start = commands.add_parser("start-stage")
    start.add_argument("--run-id", required=True)
    start.add_argument("--stage", required=True)

    finish = commands.add_parser("finish-stage")
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--stage", required=True)
    finish.add_argument("--status", choices=("success", "partial_success"), required=True)
    finish.add_argument("--counts", default="{}")

    finish_run_parser = commands.add_parser("finish-run")
    finish_run_parser.add_argument("--run-id", required=True)
    finish_run_parser.add_argument(
        "--status", choices=("auto", "success", "partial_success"), required=True
    )
    finish_run_parser.add_argument("--summary", default="{}")

    fail = commands.add_parser("fail")
    fail.add_argument("--run-id", required=True)
    fail.add_argument("--code", required=True)
    fail.add_argument("--calendar-attempt", action="store_true")
    fail.add_argument("--tournament", default="nhl")

    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            create_run(args.run_id, args.tournament, args.reason)
        elif args.action == "claim":
            print(claim_executor(args.run_id, args.owner_id))
        elif args.action == "heartbeat":
            try:
                generation = int(os.environ["SF_DATA_CYCLE_GENERATION"])
            except (KeyError, ValueError) as exc:
                raise ValueError("Executor generation is not configured") from exc
            heartbeat_executor(args.run_id, owner_generation=generation)
        elif args.action == "owner-info":
            print(
                json.dumps(get_executor_owner(args.run_id), default=_json_default, sort_keys=True)
            )
        elif args.action == "recover":
            recover_executor(args.run_id, HostStopEvidence.from_json(args.evidence))
        elif args.action == "start-stage":
            start_stage(args.run_id, args.stage)
        elif args.action == "finish-stage":
            finish_stage(
                args.run_id,
                args.stage,
                status=args.status,
                counts=_parse_counts(args.counts),
            )
        elif args.action == "finish-run":
            finish_run(args.run_id, status=args.status, summary=_parse_counts(args.summary))
        elif args.action == "fail":
            fail_run(
                args.run_id,
                failure_code=args.code,
                tournament=args.tournament if args.calendar_attempt else None,
            )
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        logger.error("Data Cycle lifecycle action failed: action=%s", args.action)
        return 1


def _parse_counts(raw: str) -> dict[str, int]:
    """Принять только безопасную map name → nonnegative integer counters."""
    value = json.loads(raw)
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, int) or item < 0
        for key, item in value.items()
    ):
        raise ValueError("Invalid summary counters")
    return value


def _json_default(value: object) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    raise TypeError("Unsupported JSON value")


if __name__ == "__main__":
    sys.exit(main())
