"""CLI production boundary для canonical prediction freshness gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sports_forecast.config.loaders import load_tournament_quality_gate_config
from sports_forecast.orchestration.canonical_refresh_gate import run_canonical_freshness_gate
from sports_forecast.service.db.engine import get_session
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Запустить один idempotent canonical gate по profile турнира."""
    parser = argparse.ArgumentParser(description="Canonical freshness gate.")
    parser.add_argument("--tournament", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        profile = load_tournament_quality_gate_config(args.tournament)
        with get_session() as session:
            outcome = run_canonical_freshness_gate(
                session=session,
                run_id=args.run_id,
                tournament=args.tournament,
                refreshed_at=datetime.now(UTC),
                match_duration_minutes=profile.match_duration_minutes,
                provider_grace_minutes=profile.provider_grace_minutes,
            )
    except Exception:
        logger.exception("Canonical freshness gate не выполнен tournament=%s", args.tournament)
        return 1
    if outcome.already_finished:
        logger.info("Canonical freshness gate уже завершён run_id=%s", args.run_id)
        return 0
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
