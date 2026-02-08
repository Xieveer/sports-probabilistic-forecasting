"""
Утилиты для работы с колонками букмекерских коэффициентов.

Определяет имена колонок с коэффициентами на основе MarketSpec конфигурации.

Examples:
    >>> col = get_odds_column_name(cfg.market_spec)
    >>> # "odds_total_over_6.5"

    >>> col = get_odds_column_name(cfg.market_spec)
    >>> # "odds_home_win"
"""

from __future__ import annotations

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

# Маппинг market_spec → шаблон имени колонки с коэффициентами
_ODDS_COLUMN_TEMPLATES: dict[str, str] = {
    "winner_home": "odds_home_win",
    "winner_away": "odds_away_win",
    "total_over": "odds_total_over_{line}",
    "total_under": "odds_total_under_{line}",
    "handicap_home": "odds_handicap_home_{line}",
    "handicap_away": "odds_handicap_away_{line}",
}


def get_odds_column_name(market_spec: DictConfig) -> str | None:
    """Определить имя колонки с коэффициентами для текущего MarketSpec.

    Использует шаблоны на основе ``market_spec.name`` и ``market_spec.line``.

    Args:
        market_spec: Конфигурация MarketSpec.

    Returns:
        Имя колонки с коэффициентами или None если не определено.

    Examples:
        >>> # Total over 6.5
        >>> get_odds_column_name(cfg.market_spec)
        'odds_total_over_6.5'

        >>> # Winner
        >>> get_odds_column_name(cfg.market_spec)
        'odds_home_win'
    """
    spec_name = market_spec.name
    template = _ODDS_COLUMN_TEMPLATES.get(spec_name)

    if template is None:
        logger.warning(
            "Шаблон odds column не найден для market_spec '%s'. "
            "Бизнес-метрики (BettingSimulator) будут пропущены.",
            spec_name,
        )
        return None

    # Подставляем line если есть placeholder
    if "{line}" in template:
        line = market_spec.get("line")
        if line is None:
            logger.warning(
                "market_spec.line не задан для '%s'. Невозможно определить odds column.",
                spec_name,
            )
            return None
        template = template.format(line=line)

    return template


def get_odds_column_long_format(market_spec: DictConfig, side: str) -> str | None:
    """Определить имя колонки с коэффициентами для long format.

    В long format каждая строка — один игрок. Для winner market
    нужно знать, на какой стороне (home/away) стоит текущий игрок.

    Args:
        market_spec: Конфигурация MarketSpec.
        side: Сторона текущего игрока (``"h"`` или ``"a"``).

    Returns:
        Имя колонки с коэффициентами или None.

    Examples:
        >>> get_odds_column_long_format(cfg.market_spec, "h")
        'odds_home_win'
        >>> get_odds_column_long_format(cfg.market_spec, "a")
        'odds_away_win'
    """
    if market_spec.name == "winner":
        if side == "h":
            return "odds_home_win"
        if side == "a":
            return "odds_away_win"
        logger.warning("Неизвестная сторона '%s' для long format", side)
        return None

    # Для total markets в long format — то же самое что в wide
    return get_odds_column_name(market_spec)


def find_odds_column(df: pd.DataFrame, market_spec: DictConfig) -> str | None:
    """Найти колонку с коэффициентами в DataFrame.

    Сначала пытается определить точное имя по шаблону,
    затем проверяет наличие в DataFrame.

    Args:
        df: DataFrame с данными.
        market_spec: Конфигурация MarketSpec.

    Returns:
        Имя колонки или None если не найдена.

    Examples:
        >>> col = find_odds_column(df, cfg.market_spec)
        >>> if col:
        ...     odds = df[col]
    """
    col_name = get_odds_column_name(market_spec)

    if col_name is None:
        return None

    if col_name in df.columns:
        logger.info("Найдена odds column: '%s'", col_name)
        return col_name

    # Пробуем вариации (разные форматы числа в имени)
    line = market_spec.get("line")
    if line is not None:
        # Пробуем с целым числом (6 вместо 6.0)
        alt_name = col_name.replace(str(line), str(int(line)))
        if alt_name != col_name and alt_name in df.columns:
            logger.info("Найдена odds column (alt): '%s'", alt_name)
            return alt_name

        # Пробуем с нижним подчёркиванием вместо точки
        alt_name = col_name.replace(".", "_")
        if alt_name in df.columns:
            logger.info("Найдена odds column (underscore): '%s'", alt_name)
            return alt_name

    logger.warning(
        "Odds column '%s' не найдена в DataFrame. "
        "Бизнес-метрики будут пропущены. "
        "Доступные odds колонки: %s",
        col_name,
        [c for c in df.columns if "odds" in c.lower()],
    )
    return None
