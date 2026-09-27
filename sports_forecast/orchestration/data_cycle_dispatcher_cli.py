"""Один безопасный dispatcher tick для установленного pipeline."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from sports_forecast.service.data_cycle_control import dispatch_due_run
from sports_forecast.service.db.engine import get_control_session
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Обновить heartbeat, создать due run и вывести только его UUID для host bridge."""
    parser = argparse.ArgumentParser(description="Data Cycle dispatcher tick")
    parser.add_argument("--pipeline", choices=("nhl",), required=True)
    parser.add_argument("--dispatcher-id", default="nhl-host")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        with get_control_session() as session:
            run, _missed_slots = dispatch_due_run(
                session,
                args.pipeline,
                args.dispatcher_id,
                now=now,
            )
            if run is None:
                run_id = ""
            elif run.status == "waiting":
                run_id = run.run_id
            elif run.executor_stalled_at is not None:
                run_id = f"stalled:{run.run_id}"
            else:
                run_id = ""
        print(run_id)
        return 0
    except (OSError, ValueError, SQLAlchemyError):
        logger.error("Data Cycle dispatcher tick failed: pipeline=%s", args.pipeline)
        return 1


if __name__ == "__main__":
    sys.exit(main())
