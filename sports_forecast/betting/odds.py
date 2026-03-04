"""
Утилиты для работы с колонками букмекерских коэффициентов.

Определяет имена колонок с коэффициентами на основе MarketSpec конфигурации.
Парсинг raw odds dict из колонки ``odds_raw`` (passthrough от ingest-слоя).

Examples:
    >>> col = get_odds_column_name(cfg.market_spec)
    >>> # "odds_total_over_6.5"

    >>> odds_series = extract_odds_from_raw(test_df, cfg.market_spec)
    >>> odds_series.head()
    0    1.48
    1    2.45
"""

from __future__ import annotations

import ast

import numpy as np
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


# ============================================================================
# ПАРСИНГ ODDS_RAW → ЧИСЛОВЫЕ КОЭФФИЦИЕНТЫ
# ============================================================================


def _parse_odds_dict(raw_value: object) -> dict | None:
    """Безопасно распарсить строку-словарь odds_raw в dict.

    Обрабатывает форматы: ``{'1': 1.48, '2': 2.45}`` (Python dict literal)
    и ``{"1": 1.48, "2": 2.45}`` (JSON-like).

    Args:
        raw_value: Значение из колонки ``odds_raw`` (str, dict или NaN).

    Returns:
        dict с коэффициентами или None если парсинг невозможен.
    """
    if raw_value is None or (isinstance(raw_value, float) and np.isnan(raw_value)):
        return None
    if isinstance(raw_value, dict):
        return raw_value
    raw_str = str(raw_value).strip()
    if not raw_str or raw_str in ("nan", "None", ""):
        return None
    try:
        result = ast.literal_eval(raw_str)
        return result if isinstance(result, dict) else None
    except (ValueError, SyntaxError):
        return None


def _resolve_raw_key(
    market_spec: DictConfig,
    bookmaker_cfg: DictConfig,
    side: str | None = None,
) -> str | None:
    """Определить ключ в odds dict, используя bookmaker конфиг.

    Маппинг ``market_spec.name → raw_key`` берётся из
    ``bookmaker_cfg.market_keys``, а для long-format winner —
    из ``bookmaker_cfg.side_keys``.

    Args:
        market_spec: Конфигурация рынка.
        bookmaker_cfg: Конфигурация букмекера (``conf/bookmaker/*.yaml``).
        side: Сторона игрока (``"h"`` / ``"a"``) — нужна только для
              long format ``winner`` market.

    Returns:
        Ключ словаря odds_raw или None.
    """
    spec_name = market_spec.name
    market_keys = bookmaker_cfg.get("market_keys", {})
    side_keys = bookmaker_cfg.get("side_keys", {})

    # Long-format winner: ключ зависит от стороны текущего игрока
    if spec_name == "winner" and side is not None:
        key = side_keys.get(side)
        if key is None:
            logger.debug("side_keys не содержит ключ для side='%s'", side)
            return None
        return str(key)

    # Обычный маппинг market_spec.name → raw_key (шаблон)
    raw_template = market_keys.get(spec_name)
    if raw_template is None:
        logger.warning(
            "bookmaker.market_keys не содержит ключ для market '%s'",
            spec_name,
        )
        return None
    template = str(raw_template)

    # Подстановка {line} для параметрических рынков (total, handicap)
    if "{line}" in template:
        line = market_spec.get("line")
        if line is None:
            logger.warning(
                "market_spec.line не задан для '%s', невозможно определить raw_key",
                spec_name,
            )
            return None
        template = template.replace("{line}", str(line))

    return template


def extract_odds_from_raw(
    df: pd.DataFrame,
    market_spec: DictConfig,
    bookmaker_cfg: DictConfig,
) -> pd.Series:
    """Извлечь числовые odds из колонки ``odds_raw`` для заданного рынка.

    Колонка ``odds_raw`` содержит строковое представление Python dict,
    пробрасываемое через все слои данных (ingest → clean → features → trainer).
    Маппинг ``market_spec.name → raw_key`` берётся из ``bookmaker_cfg``.

    Args:
        df: DataFrame, содержащий колонку ``odds_raw``
            (и ``side`` для long format).
        market_spec: Конфигурация рынка (определяет тип рынка и line).
        bookmaker_cfg: Конфигурация букмекера (``conf/bookmaker/*.yaml``),
            содержит ``market_keys`` и ``side_keys``.

    Returns:
        pd.Series с float odds (NaN если значение отсутствует / невалидно).

    Examples:
        >>> odds = extract_odds_from_raw(test_df, cfg.market_spec, cfg.bookmaker)
        >>> valid_mask = odds.notna() & (odds > 1.0)
        >>> odds[valid_mask].describe()
    """
    if "odds_raw" not in df.columns:
        logger.warning("Колонка 'odds_raw' не найдена в DataFrame")
        return pd.Series(np.nan, index=df.index, dtype=float)

    spec_name = market_spec.name
    data_format = market_spec.get("data_format", "wide")
    is_long_winner = spec_name == "winner" and data_format == "long"
    has_side = "side" in df.columns

    # Для статических рынков ключ одинаков для всех строк — вычисляем один раз
    static_key: str | None = None
    if not is_long_winner:
        static_key = _resolve_raw_key(market_spec, bookmaker_cfg)
        if static_key is None:
            return pd.Series(np.nan, index=df.index, dtype=float)

    result = np.full(len(df), np.nan, dtype=float)

    for i, (_idx, row) in enumerate(df.iterrows()):
        d = _parse_odds_dict(row.get("odds_raw"))
        if d is None:
            continue

        if is_long_winner and has_side:
            key = _resolve_raw_key(market_spec, bookmaker_cfg, side=row.get("side"))
        else:
            key = static_key

        if key is not None and key in d:
            try:
                val = float(d[key])
                if val > 1.0:
                    result[i] = val
            except (ValueError, TypeError):
                pass

    odds_series = pd.Series(result, index=df.index, dtype=float)
    valid_count = int(odds_series.notna().sum())
    logger.info(
        "extract_odds_from_raw: bookmaker=%s, market=%s, формат=%s, извлечено %d/%d odds",
        bookmaker_cfg.get("name", "?"),
        spec_name,
        data_format,
        valid_count,
        len(df),
    )
    return odds_series
