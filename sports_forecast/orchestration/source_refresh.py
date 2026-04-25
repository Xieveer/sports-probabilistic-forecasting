"""CLI: обновить ``source.csv`` для турнира через зарегистрированный :class:`SourceProvider`.

Используется в Airflow ``SF_SOURCE_REFRESH_CMD`` вместо ``test -f`` для турниров с
динамическим источником (например NHL ``nhl_web_api``).

Пример::

    uv run python -m sports_forecast.orchestration.source_refresh --tournament nhl
    # без post-step odds (только provider.fetch):
    uv run python -m sports_forecast.orchestration.source_refresh --tournament nhl --skip-odds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import load_paths_config, load_source_config
from sports_forecast.data.providers import (
    SourceDataNotFoundError,
    SourceProviderError,
    get_provider,
)
from sports_forecast.data.providers.odds.refresh import run_odds_refresh
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_DEFAULT_SPORT_KEY: str = "icehockey_nhl"
_DEFAULT_BOOKMAKER_KEY: str = "the_odds_api"


def _odds_post_fetch_enabled(source_cfg: DictConfig | None) -> bool:
    """True, если в source-конфиге ``odds.enabled`` явно включён коэффициентный post-step."""
    if source_cfg is None:
        return False
    odds = source_cfg.get("odds")
    if odds is None:
        return False
    raw: Any = OmegaConf.select(odds, "enabled")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("1", "true", "yes")


def _run_odds_post_fetch(tournament: str, source_cfg: DictConfig, source_csv: Path) -> None:
    """Вызвать :func:`run_odds_refresh` с параметрами из ``source_cfg.odds`` (fail-fast при ошибке)."""
    odds = source_cfg.get("odds") or OmegaConf.create({})
    bookmaker_key = str(odds.get("bookmaker") or _DEFAULT_BOOKMAKER_KEY)
    sport_key = str(odds.get("sport_key") or _DEFAULT_SPORT_KEY)
    logger.info(
        "odds refresh: start tournament=%s bookmaker=%s source_csv=%s",
        tournament,
        bookmaker_key,
        source_csv,
    )
    result = run_odds_refresh(
        tournament=tournament,
        sport_key=sport_key,
        bookmaker_key=bookmaker_key,
        source_config_name=tournament,
        source_csv_path=source_csv,
    )
    logger.info(
        "odds refresh: finished source_csv=%s new_odds_rows=%d store_rows=%d merged_source=%s "
        "segment=%s..%s quota_hit=%s api_remaining=%s",
        source_csv,
        result.new_odds_rows,
        result.store_rows,
        result.merged_source,
        result.segment.date_from,
        result.segment.date_to,
        result.quota_hit,
        result.requests_remaining,
    )


def refresh_source(tournament: str, *, skip_odds: bool = False) -> Path:
    """Вызвать ``provider.fetch`` для турнира; при ``odds.enabled`` — инкрементальный odds-refresh (post-step).

    Args:
        tournament: Имя каталога под ``data/source`` (как в ingest).
        skip_odds: Если True, не вызывать :func:`run_odds_refresh` (дебаг / hotfix).

    Returns:
        Путь к ``source.csv``.

    Raises:
        SourceDataNotFoundError: Нет локального файла для file-провайдера.
        SourceProviderError: Ошибка загрузки NHL/Web и т.п.
        ValueError, OSError: Ошибка odds-refresh (без глотания: пайплайн падает).
    """
    paths_cfg = load_paths_config()
    try:
        source_cfg = load_source_config(tournament)
    except FileNotFoundError:
        source_cfg = None
    provider = get_provider(source_cfg, paths_cfg)
    path = provider.fetch(tournament)
    if not skip_odds and source_cfg is not None and _odds_post_fetch_enabled(source_cfg):
        _run_odds_post_fetch(tournament, source_cfg, path)
    return path


def main(argv: list[str] | None = None) -> int:
    """Точка входа для ``python -m sports_forecast.orchestration.source_refresh``."""
    parser = argparse.ArgumentParser(description="Обновить source.csv для турнира")
    parser.add_argument(
        "--tournament",
        required=True,
        help="Имя турнира (каталог под data/source)",
    )
    parser.add_argument(
        "--skip-odds",
        action="store_true",
        default=False,
        help="Не вызывать инкрементальный odds-refresh после успешного provider.fetch",
    )
    args = parser.parse_args(argv)
    try:
        path = refresh_source(args.tournament, skip_odds=args.skip_odds)
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
