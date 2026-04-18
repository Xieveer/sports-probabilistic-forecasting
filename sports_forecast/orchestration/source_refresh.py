"""CLI: обновить ``source.csv`` для турнира через зарегистрированный :class:`SourceProvider`.

Используется в Airflow ``SF_SOURCE_REFRESH_CMD`` вместо ``test -f`` для турниров с
динамическим источником (например NHL ``nhl_web_api``).

Пример::

    uv run python -m sports_forecast.orchestration.source_refresh --tournament nhl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sports_forecast.config.loaders import load_paths_config, load_source_config
from sports_forecast.data.providers import (
    SourceDataNotFoundError,
    SourceProviderError,
    get_provider,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def refresh_source(tournament: str) -> Path:
    """Вызвать ``provider.fetch`` для турнира или проверить наличие CSV (file provider).

    Args:
        tournament: Имя каталога под ``data/source`` (как в ingest).

    Returns:
        Путь к ``source.csv``.

    Raises:
        SourceDataNotFoundError: Нет локального файла для file-провайдера.
        SourceProviderError: Ошибка загрузки NHL/Web и т.п.
    """
    paths_cfg = load_paths_config()
    try:
        source_cfg = load_source_config(tournament)
    except FileNotFoundError:
        source_cfg = None
    provider = get_provider(source_cfg, paths_cfg)
    return provider.fetch(tournament)


def main(argv: list[str] | None = None) -> int:
    """Точка входа для ``python -m sports_forecast.orchestration.source_refresh``."""
    parser = argparse.ArgumentParser(description="Обновить source.csv для турнира")
    parser.add_argument(
        "--tournament",
        required=True,
        help="Имя турнира (каталог под data/source)",
    )
    args = parser.parse_args(argv)
    try:
        path = refresh_source(args.tournament)
    except SourceDataNotFoundError as e:
        logger.error("%s", e)
        return 1
    except SourceProviderError as e:
        logger.error("Ошибка провайдера: %s", e)
        return 1
    logger.info("source refresh OK → %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
