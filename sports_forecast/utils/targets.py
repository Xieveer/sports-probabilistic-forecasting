"""
Target Computation Module для архитектуры v2.0.

Вычисление таргетов на основе MarketSpec вместо старых target_sources.
"""

import logging

import pandas as pd
from omegaconf import DictConfig


logger = logging.getLogger(__name__)


class TargetComputationError(Exception):
    """Ошибка при вычислении таргета."""

    pass


def _compute_target_from_source(
    df: pd.DataFrame,
    market_spec: DictConfig,
    tournament_cfg: DictConfig,
    line: float | None = None,
) -> pd.Series:
    """
    Вычислить таргет используя target_sources из tournament config (НОВАЯ АРХИТЕКТУРА).

    Args:
        df: DataFrame с данными
        market_spec: cfg.market_spec конфигурация
        tournament_cfg: cfg.tournament конфигурация
        line: Линия для total/handicap markets

    Returns:
        Series с бинарным таргетом (0/1)

    Raises:
        TargetComputationError: Если вычисление невозможно
    """
    target_source_key = market_spec.target_source_key
    target_name = market_spec.get("target_name", "target")
    data_format = market_spec.data_format

    if not hasattr(tournament_cfg, "target_sources"):
        raise TargetComputationError(
            f"tournament '{tournament_cfg.name}' не содержит target_sources"
        )

    if target_source_key not in tournament_cfg.target_sources:
        available = list(tournament_cfg.target_sources.keys())
        raise TargetComputationError(
            f"target_source_key '{target_source_key}' не найден в tournament.target_sources. "
            f"Доступные: {available}"
        )

    target_spec = tournament_cfg.target_sources[target_source_key]
    comparison = target_spec.comparison

    # Получаем колонки в зависимости от формата
    if target_spec.format == "long":
        col_a = target_spec.player_column
        col_b = target_spec.opponent_column
    else:  # wide
        col_a = target_spec.home_column
        col_b = target_spec.away_column

    # Проверяем наличие колонок
    for col in [col_a, col_b]:
        if col not in df.columns:
            raise TargetComputationError(
                f"Колонка '{col}' не найдена в датафрейме. Доступные: {list(df.columns)[:20]}..."
            )

    # Вычисляем таргет
    if comparison == "greater":
        target = (df[col_a] > df[col_b]).astype(int)
        logger.info(
            "✓ Таргет '%s': %s > %s, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            data_format,
            target.mean() * 100,
        )
    elif comparison == "total_over":
        if line is None:
            line = market_spec.get("line")
        if line is None or line == "???":
            raise TargetComputationError("Line обязательна для total_over!")
        target = ((df[col_a] + df[col_b]) > line).astype(int)
        logger.info(
            "✓ Таргет '%s': (%s + %s) > %.1f, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            line,
            data_format,
            target.mean() * 100,
        )
    elif comparison == "total_under":
        if line is None:
            line = market_spec.get("line")
        if line is None:
            raise TargetComputationError("Line обязательна для total_under!")
        target = ((df[col_a] + df[col_b]) < line).astype(int)
        logger.info(
            "✓ Таргет '%s': (%s + %s) < %.1f, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            line,
            data_format,
            target.mean() * 100,
        )
    else:
        raise TargetComputationError(f"Неизвестный comparison: {comparison}")

    return target  # type: ignore[no-any-return]


def compute_target_from_market_spec(
    df: pd.DataFrame,
    market_spec: DictConfig,
    tournament_cfg: DictConfig | None = None,
    line: float | None = None,
) -> pd.Series:
    """
    Вычислить таргет на основе MarketSpec (архитектура v2.0).

    Args:
        df: DataFrame с данными
        market_spec: cfg.market_spec конфигурация
        tournament_cfg: cfg.tournament конфигурация (для target_sources)
        line: Линия для total/handicap markets (override market_spec.line)

    Returns:
        Series с бинарным таргетом (0/1)

    Raises:
        TargetComputationError: Если вычисление невозможно

    Examples:
        >>> # Winner (long format) - НОВАЯ АРХИТЕКТУРА
        >>> target = compute_target_from_market_spec(df, cfg.market_spec, cfg.tournament)

        >>> # Total over 6.5 - НОВАЯ АРХИТЕКТУРА
        >>> target = compute_target_from_market_spec(df, cfg.market_spec, cfg.tournament, line=6.5)
    """
    # НОВАЯ АРХИТЕКТУРА: Используем target_source_key
    if hasattr(market_spec, "target_source_key") and tournament_cfg:
        return _compute_target_from_source(df, market_spec, tournament_cfg, line)

    # СТАРАЯ АРХИТЕКТУРА (для обратной совместимости)
    # Получаем параметры
    market_family = market_spec.market_family
    side = market_spec.get("side")
    data_format = market_spec.data_format

    # Получаем source columns
    if not hasattr(market_spec, "target"):
        raise TargetComputationError(
            f"market_spec '{market_spec.name}' не содержит ни target_source_key, ни target секцию. "
            "Обновите конфиг на новую архитектуру!"
        )

    source_columns = market_spec.target.get("source_columns", [])
    # formula = market_spec.target.get("formula")  # TODO: implement formula-based targets
    target_name = market_spec.target.get("name", "target")

    # Проверяем наличие колонок
    for col in source_columns:
        if col not in df.columns:
            raise TargetComputationError(
                f"Колонка '{col}' не найдена в датафрейме. Доступные: {list(df.columns)[:20]}..."
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
                "Line обязательна для total markets! "
                "Укажите market_spec.line=6.5 или передайте параметр line"
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
            f"Неизвестный market_family: {market_family}. Поддерживаются: winner, total, handicap"
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
                f"winner_home требует 2 колонки [home_points, away_points], получено: {source_cols}"
            )
        home_col, away_col = source_cols
        target = (df[home_col] > df[away_col]).astype(int)
        logger.debug("Winner home: %s > %s", home_col, away_col)

    elif side == "away":
        # Победа гостей: away_points > home_points
        if len(source_cols) != 2:
            raise TargetComputationError("winner_away требует 2 колонки [home_points, away_points]")
        home_col, away_col = source_cols
        target = (df[away_col] > df[home_col]).astype(int)
        logger.debug("Winner away: %s > %s", away_col, home_col)

    else:
        raise TargetComputationError(
            f"Неизвестный side для winner: {side}. Поддерживаются: home, away"
        )

    return target  # type: ignore[no-any-return]


def _compute_total_target(df: pd.DataFrame, market_spec: DictConfig, line: float) -> pd.Series:
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
            f"total markets требуют 2 колонки [home_points, away_points], получено: {source_cols}"
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

    return target  # type: ignore[no-any-return]


def _compute_handicap_target(df: pd.DataFrame, market_spec: DictConfig, line: float) -> pd.Series:
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
            "handicap markets требуют 2 колонки [home_points, away_points]"
        )

    home_col, away_col = source_cols

    # Применяем фору
    if side == "home":
        # Фора на хозяев: (home + line) > away
        result = df[home_col] + line
        target = (result > df[away_col]).astype(int)
        logger.debug("Handicap home %.1f: (%s + %.1f) > %s", line, home_col, line, away_col)

    elif side == "away":
        # Фора на гостей: (away + line) > home
        result = df[away_col] + line
        target = (result > df[home_col]).astype(int)
        logger.debug("Handicap away %.1f: (%s + %.1f) > %s", line, away_col, line, home_col)

    else:
        raise TargetComputationError(
            f"Неизвестный side для handicap: {side}. Поддерживаются: home, away"
        )

    return target  # type: ignore[no-any-return]


def get_target_name(market_spec: DictConfig, line: float | None = None) -> str:
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
    # НОВАЯ АРХИТЕКТУРА: используем target_name
    if hasattr(market_spec, "target_name"):
        base_name = market_spec.target_name
    # СТАРАЯ АРХИТЕКТУРА: используем target.name
    elif hasattr(market_spec, "target"):
        base_name = market_spec.target.get("name", "target")
    else:
        base_name = "target"

    # Подставляем line если есть placeholder {line} или добавляем line для total/handicap
    market_family = market_spec.get("market_family", "")
    if market_family in ["total", "handicap"]:
        if line is None:
            line = market_spec.get("line")
        if line is not None:
            # Добавляем линию к имени
            base_name = f"{base_name}_{str(line).replace('.', '_')}"

    return base_name  # type: ignore[no-any-return]
