"""Cron/systemd entrypoint: полный refresh-пайплайн с ``flock`` (как Airflow DAG).

Пайплайн на турнир: source → ingest → clean → features → materialize.
Блокировка и аргументы по умолчанию совместимы с DAG Airflow
``airflow/dags/dag_data_refresh.py``.

Утренний NHL (12:00 MSK): см. ``airflow/dags/dag_nhl_morning_refresh.py`` и
``docs/source/nhl_local_operations.rst`` (R37.6); ручной эквивалент — ``make nhl-morning-refresh-dry-run``
(без ``--dry-run`` для выполнения).

Пример (NHL, advanced фичи)::

    uv run python -m sports_forecast.orchestration.cron_refresh --tournaments nhl

Cron::

    0 6 * * * cd /opt/sports-forecast && SF_PROJECT_DIR=/opt/sports-forecast \\
      uv run python -m sports_forecast.orchestration.cron_refresh --tournaments nhl \\
      >> /var/log/sf_nhl_refresh.log 2>&1

Альтернатива: стек Airflow (``airflow/dags/dag_data_refresh.py``) или профиль compose
с отдельным one-shot контейнером worker.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


def _default_source_command(uv_run: str) -> str:
    return f"{uv_run} python -m sports_forecast.orchestration.source_refresh --tournament {{tournament}}"


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI definitions for :func:`main`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tournaments",
        default=os.environ.get("SF_REFRESH_TOURNAMENTS", "nhl"),
        help="Список tournament через запятую (env SF_REFRESH_TOURNAMENTS)",
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("SF_PROJECT_DIR", "."),
        help="Корень репозитория на сервере (env SF_PROJECT_DIR)",
    )
    parser.add_argument(
        "--uv-run",
        default=os.environ.get("SF_UV_RUN", "uv run"),
        help="Префикс запуска Python (env SF_UV_RUN), например «uv run»",
    )
    parser.add_argument(
        "--features",
        default=os.environ.get("SF_FEATURES_CONFIG", "advanced"),
        help="Аргумент features для features_build (env SF_FEATURES_CONFIG)",
    )
    parser.add_argument(
        "--market",
        default=os.environ.get("SF_MATERIALIZE_MARKET", "winner"),
        help="Рынок materialize (env SF_MATERIALIZE_MARKET)",
    )
    parser.add_argument(
        "--market-spec",
        default=os.environ.get("SF_MATERIALIZE_SPEC", "winner"),
        dest="market_spec",
        help="Спецификация рынка (env SF_MATERIALIZE_SPEC)",
    )
    parser.add_argument(
        "--lock-file",
        default=os.environ.get("SF_REFRESH_LOCK_FILE", "/tmp/sf_refresh_pipeline.lock"),
        help="Файл блокировки flock (env SF_REFRESH_LOCK_FILE)",
    )
    parser.add_argument(
        "--lock-wait-seconds",
        type=int,
        default=int(os.environ.get("SF_REFRESH_LOCK_WAIT_SECONDS", "300")),
        help="Таймаут ожидания блокировки (env SF_REFRESH_LOCK_WAIT_SECONDS)",
    )
    parser.add_argument(
        "--source-cmd",
        default=os.environ.get("SF_SOURCE_REFRESH_CMD", ""),
        help=(
            "Команда source-стадии с плейсхолдером {tournament} "
            "(по умолчанию SF_SOURCE_REFRESH_CMD или uv run … source_refresh)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только вывести shell-команду, не выполнять",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse args, build bash pipeline, run or print it."""
    args = build_arg_parser().parse_args(argv)
    project_dir = str(Path(args.project_dir).resolve())
    source_cmd = args.source_cmd.strip() or _default_source_command(args.uv_run)

    command = build_refresh_per_tournament_command(
        project_dir=project_dir,
        uv_run=args.uv_run,
        tournaments_expr=args.tournaments,
        features_config=args.features,
        market=args.market,
        market_spec=args.market_spec,
        source_cmd=source_cmd,
        lock_file=args.lock_file,
        lock_wait_seconds=args.lock_wait_seconds,
    )
    if args.dry_run:
        print(command)
        return 0
    subprocess.run(["/bin/bash", "-c", command], check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
