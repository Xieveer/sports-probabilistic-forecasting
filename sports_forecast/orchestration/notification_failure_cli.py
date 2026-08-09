"""CLI безопасного admin-only уведомления для Airflow."""

from __future__ import annotations

import argparse
import os

from sports_forecast.orchestration.initial_notification import notify_administrators
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Отправить краткое сообщение администраторам без деталей сбоя."""
    parser = argparse.ArgumentParser(description="Уведомить администраторов о сбое DAG.")
    parser.add_argument("--failure-kind", required=True)
    args = parser.parse_args(argv)
    admins = tuple(
        value.strip()
        for value in os.environ.get("BOT_ADMIN_USER_IDS", "").split(",")
        if value.strip()
    )
    try:
        notify_administrators(
            admin_chat_ids=admins,
            token=os.environ.get("BOT_TOKEN", ""),
            failure_kind=args.failure_kind,
        )
    except Exception:
        logger.exception("Admin notification не доставлено")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
