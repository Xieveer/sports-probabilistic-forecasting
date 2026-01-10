"""
Target Computation Module для архитектуры v2.0.

Вычисление таргетов на основе MarketSpec вместо старых target_sources.
"""

import logging
from typing import Optional

import pandas as pd
from omegaconf import DictConfig

logger = logging.getLogger(__name__)


class TargetComputationError(Exception):
    """Ошибка при вычислении таргета."""

    pass


def compute_target_from_market_spec(
    df: pd.DataFrame, market_spec: DictConfig, line: Optional[float] = None
) -> pd.Series:
    """
    Вычислить таргет на основе MarketSpec (архитектура v2.0).

    Args:
        df: DataFrame с данными
        market_spec: cfg.market_spec конфигурация
        line: Линия для total/handicap markets (override market_spec.line)

    Returns:
        Series с бинарным таргетом (0/1)

    Raises:
        TargetComputationError: Если вычисление невозможно

    Examples:
        >>> # Winner home
        >>> target = compute_target_from_market_spec(df, cfg.market_spec)
        
        >>> # Total over 6.5
        >>> target = compute_target_from_market_spec(df, cfg.market_spec, line=6.5)
    """
    # Получаем параметры
    market_family = market_spec.market_family
    side = market_spec.get("side")
    data_format = market_spec.data_format

    # Получаем source columns
    if not hasattr(market_spec, "target"):
        raise TargetComputationError(
            f"market_spec '{market_spec.name}' не содержит секцию 'target'"
        )

    source_columns = market_spec.target.get("source_columns", [])
    formula = market_spec.target.get("formula")
    target_name = market_spec.target.get("name", "target")

    # Проверяем наличие колонок
    for col in source_columns:
        if col not in df.columns:
            raise TargetComputationError(
                f"Колонка '{col}' не найдена в датафрейме. "
                f"Доступные: {list(df.columns)[:20]}..."
            )

    # Вычисляем таргет в зависимости от market family
    if market_family == "winner":
        target = _compute_winner_target(df, market_spec)

    elif market_family == "total":
        # Для total обязательна линия
        if line is None:
            line = market_spec.get("line")
        if line is None or line == "???":
            raise TargetComputationError(
                f"Line обязательна для total markets! "
                f"Укажите market_spec.line=6.5 или передайте параметр line"
            )

        target = _compute_total_target(df, market_spec, line)

    elif market_family == "handicap":
        # Для handicap обязательна линия
        if line is None:
            line = market_spec.get("line")
        if line is None:
            raise TargetComputationError("Line обязательна для handicap markets!")

        target = _compute_handicap_target(df, market_spec, line)

    else:
        raise TargetComputationError(
            f"Неизвестный market_family: {market_family}. "
            f"Поддерживаются: winner, total, handicap"
        )

    # Логируем
    logger.info(
        "✓ Таргет '%s' вычислен: market=%s, side=%s, format=%s, positive_rate=%.2f%%",
        target_name,
        market_family,
        side,
        data_format,
        target.mean() * 100,
    )

    return target


def _compute_winner_target(df: pd.DataFrame, market_spec: DictConfig) -> pd.Series:
    """
    Вычислить таргет для winner market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация

    Returns:
        Бинарный таргет (1 = победа, 0 = проигрыш)
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if side == "home":
        # Победа хозяев: home_points > away_points
        if len(source_cols) != 2:
            raise TargetComputationError(
                f"winner_home требует 2 колонки [home_points, away_points], "
                f"получено: {source_cols}"
            )
        home_col, away_col = source_cols
        target = (df[home_col] > df[away_col]).astype(int)
        logger.debug("Winner home: %s > %s", home_col, away_col)

    elif side == "away":
        # Победа гостей: away_points > home_points
        if len(source_cols) != 2:
            raise TargetComputationError(
                f"winner_away требует 2 колонки [home_points, away_points]"
            )
        home_col, away_col = source_cols
        target = (df[away_col] > df[home_col]).astype(int)
        logger.debug("Winner away: %s > %s", away_col, home_col)

    else:
        raise TargetComputationError(
            f"Неизвестный side для winner: {side}. Поддерживаются: home, away"
        )

    return target


def _compute_total_target(
    df: pd.DataFrame, market_spec: DictConfig, line: float
) -> pd.Series:
    """
    Вычислить таргет для total market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация
        line: Линия тотала (например, 6.5)

    Returns:
        Бинарный таргет (1 = over/under, 0 = иначе)
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if len(source_cols) != 2:
        raise TargetComputationError(
            f"total markets требуют 2 колонки [home_points, away_points], "
            f"получено: {source_cols}"
        )

    home_col, away_col = source_cols

    # Вычисляем total
    total = df[home_col] + df[away_col]

    # Применяем comparison
    if side == "over":
        target = (total > line).astype(int)
        logger.debug("Total over %.1f: (%s + %s) > %.1f", line, home_col, away_col, line)

    elif side == "under":
        target = (total < line).astype(int)
        logger.debug("Total under %.1f: (%s + %s) < %.1f", line, home_col, away_col, line)

    else:
        raise TargetComputationError(
            f"Неизвестный side для total: {side}. Поддерживаются: over, under"
        )

    return target


def _compute_handicap_target(
    df: pd.DataFrame, market_spec: DictConfig, line: float
) -> pd.Series:
    """
    Вычислить таргет для handicap market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация
        line: Линия форы (например, -1.5)

    Returns:
        Бинарный таргет
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if len(source_cols) != 2:
        raise TargetComputationError(
            f"handicap markets требуют 2 колонки [home_points, away_points]"
        )

    home_col, away_col = source_cols

    # Применяем фору
    if side == "home":
        # Фора на хозяев: (home + line) > away
        result = df[home_col] + line
        target = (result > df[away_col]).astype(int)
        logger.debug(
            "Handicap home %.1f: (%s + %.1f) > %s", line, home_col, line, away_col
        )

    elif side == "away":
        # Фора на гостей: (away + line) > home
        result = df[away_col] + line
        target = (result > df[home_col]).astype(int)
        logger.debug(
            "Handicap away %.1f: (%s + %.1f) > %s", line, away_col, line, home_col
        )

    else:
        raise TargetComputationError(
            f"Неизвестный side для handicap: {side}. Поддерживаются: home, away"
        )

    return target


def get_target_name(market_spec: DictConfig, line: Optional[float] = None) -> str:
    """
    Получить имя таргета на основе MarketSpec.

    Args:
        market_spec: cfg.market_spec
        line: Линия (для total/handicap)

    Returns:
        Имя таргета (например, "target_total_over_6.5")

    Examples:
        >>> name = get_target_name(cfg.market_spec, line=6.5)
        >>> # "target_total_over_6.5"
    """
    base_name = market_spec.target.get("name", "target")

    # Подставляем line если есть placeholder {line}
    if "{line}" in base_name:
        if line is None:
            line = market_spec.get("line")
        if line is not None:
            base_name = base_name.replace("{line}", str(line).replace(".", "_"))

    return base_name

