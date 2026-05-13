"""
Утилиты для работы с колонками букмекерских коэффициентов.

Определяет имена колонок с коэффициентами на основе MarketSpec конфигурации.
Парсинг raw odds dict из колонки ``odds_raw`` (passthrough от ingest-слоя или
synthetic-сборки на clean из merge wide, R26).

Единый вход для тренера: :func:`extract_betting_odds` (``odds_raw`` и опционально
``odds_transport.mode=wide_columns`` в профиле букмекера).

Examples:
    >>> col = get_odds_column_name(cfg.market_spec)
    >>> # "odds_total_over_6.5"

    >>> odds_series = extract_betting_odds(test_df, cfg.market_spec, cfg.bookmaker)
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
    spec_name = market_spec.name
    if spec_name in ("winner", "winner_withOT"):
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


# ПАРСИНГ ODDS_RAW → ЧИСЛОВЫЕ КОЭФФИЦИЕНТЫ


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

    # Long-format winner / winner_withOT (NHL OT): ключ зависит от стороны текущего игрока
    if spec_name in ("winner", "winner_withOT") and side is not None:
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
    is_long_winner = spec_name in ("winner", "winner_withOT") and data_format == "long"
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


def _first_valid_odds_from_columns(row: pd.Series, candidates: list[str]) -> float | None:
    """Первый decimal > 1 из списка колонок строки (для synthetic odds_raw)."""
    for col in candidates:
        if col not in row.index:
            continue
        raw = row[col]
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 1.0:
            return val
    return None


def _synthetic_odds_raw_applicable(df: pd.DataFrame, synthetic_cfg: dict | DictConfig) -> bool:
    """Проверить, есть ли в данных колонки-кандидаты под секцию ``synthetic_odds_raw``."""
    h2h = synthetic_cfg.get("winner_withOT_h2h") or synthetic_cfg.get("winner_h2h")
    if h2h:
        kmap = h2h.get("key_to_column_candidates") or {}
        for _k, cols in dict(kmap).items():
            cand = [c for c in (list(cols) if cols is not None else []) if c in df.columns]
            if cand:
                return True
    tot = synthetic_cfg.get("total_withOT")
    if tot:
        for key in (
            "line_column_candidates",
            "over_column_candidates",
            "under_column_candidates",
        ):
            cols = tot.get(key) or []
            if any(c in df.columns for c in list(cols)):
                return True
    return False


def build_synthetic_odds_raw_series(
    df: pd.DataFrame,
    synthetic_cfg: dict | DictConfig,
) -> pd.Series:
    """Построить колонку ``odds_raw`` (строка Python-dict) из wide merge-колонок.

    Используется на clean (NHL + The Odds API): тренер затем вызывает
    ``extract_odds_from_raw`` с теми же ``market_keys`` / ``side_keys``, что и для Fonbet.

    Args:
        df: Строки raw/interim с ``pinnacle_*`` close колонками.
        synthetic_cfg: Узел ``bookmaker.synthetic_odds_raw`` из ``the_odds_api.yaml``.

    Returns:
        Series строк-словарей или NA, индекс как у ``df``.
    """
    h2h = synthetic_cfg.get("winner_withOT_h2h") or synthetic_cfg.get("winner_h2h")
    tot = synthetic_cfg.get("total_withOT")
    keys_h2h: dict[str, list[str]] = {}
    if h2h:
        kmap = h2h.get("key_to_column_candidates") or {}
        for k, cols in dict(kmap).items():
            keys_h2h[str(k)] = [
                c for c in (list(cols) if cols is not None else []) if c in df.columns
            ]

    line_cands: list[str] = []
    over_cands: list[str] = []
    under_cands: list[str] = []
    over_tpl = "to_{line}"
    under_tpl = "tu_{line}"
    if tot:
        line_cands = [c for c in (tot.get("line_column_candidates") or []) if c in df.columns]
        over_cands = [c for c in (tot.get("over_column_candidates") or []) if c in df.columns]
        under_cands = [c for c in (tot.get("under_column_candidates") or []) if c in df.columns]
        over_tpl = str(tot.get("over_key_template") or over_tpl)
        under_tpl = str(tot.get("under_key_template") or under_tpl)

    out: list[str | None] = []
    for _idx, row in df.iterrows():
        d: dict[str, float] = {}
        for raw_key, cols in keys_h2h.items():
            v = _first_valid_odds_from_columns(row, cols)
            if v is not None:
                d[raw_key] = v
        if line_cands and over_cands and under_cands:
            line_val = _first_valid_odds_from_columns(row, line_cands)
            if line_val is not None:
                line_s = str(line_val)
                o = _first_valid_odds_from_columns(row, over_cands)
                u = _first_valid_odds_from_columns(row, under_cands)
                if o is not None:
                    d[over_tpl.replace("{line}", line_s)] = o
                if u is not None:
                    d[under_tpl.replace("{line}", line_s)] = u
        out.append(str(d) if d else None)
    return pd.Series(out, index=df.index, dtype=object)


def try_attach_synthetic_odds_raw_column(
    df: pd.DataFrame,
    bookmaker_node: DictConfig,
    tournament_name: str,
    clean_cfg: DictConfig | None = None,
) -> pd.DataFrame:
    """Добавить колонку ``odds_raw`` из ``synthetic_odds_raw``, если применимо.

    Не перезаписывает непустой ``odds_raw``, если в ``clean_cfg`` не задан
    ``synthetic_odds_raw_force: true``.

    Args:
        df: Датафрейм после derived_columns, до ``select_columns``.
        bookmaker_node: Узел ``bookmaker`` (как в ``load_bookmaker_config``).
        tournament_name: Имя турнира (логирование).
        clean_cfg: Секция ``data_clean`` турнира.

    Returns:
        Копия или исходный ``df`` с возможной колонкой ``odds_raw``.
    """
    syn = bookmaker_node.get("synthetic_odds_raw")
    if not syn:
        return df
    if not _synthetic_odds_raw_applicable(df, syn):
        return df
    force = bool(clean_cfg and clean_cfg.get("synthetic_odds_raw_force"))
    if "odds_raw" in df.columns and not force:
        ser_ex = df["odds_raw"]
        if ser_ex.notna().any():
            non_empty = ser_ex.astype(str).str.strip()
            has_content = (
                (non_empty != "") & (non_empty.str.lower() != "nan") & (non_empty != "None")
            )
            if has_content.any():
                return df
    series = build_synthetic_odds_raw_series(df, syn)
    out = df.copy()
    out["odds_raw"] = series
    n_ok = int(series.notna().sum())
    logger.info(
        "Турнир %s: synthetic odds_raw из merge wide (R26), строк с dict: %d/%d",
        tournament_name,
        n_ok,
        len(df),
    )
    return out


def _extract_odds_wide_transport(
    df: pd.DataFrame,
    market_spec: DictConfig,
    transport: dict | DictConfig,
) -> pd.Series:
    """Decimal из merge wide без ``odds_raw`` (long winner / winner_withOT)."""
    spec_name = market_spec.name
    data_format = market_spec.get("data_format", "wide")
    long_specs = set(transport.get("long_winner_specs") or ["winner", "winner_withOT"])
    if spec_name not in long_specs or data_format != "long" or "side" not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    home_cols = list(transport.get("home_close_column_candidates") or [])
    away_cols = list(transport.get("away_close_column_candidates") or [])
    home_col = next((c for c in home_cols if c in df.columns), None)
    away_col = next((c for c in away_cols if c in df.columns), None)
    if home_col is None or away_col is None:
        return pd.Series(np.nan, index=df.index, dtype=float)
    side = df["side"].astype(str).str.lower()
    hclose = pd.to_numeric(df[home_col], errors="coerce")
    aclose = pd.to_numeric(df[away_col], errors="coerce")
    result = pd.Series(np.nan, index=df.index, dtype=float)
    mask_h = side == "h"
    mask_a = side == "a"
    result.loc[mask_h] = hclose.loc[mask_h]
    result.loc[mask_a] = aclose.loc[mask_a]
    return result.where(result > 1.0)


def extract_betting_odds(
    df: pd.DataFrame,
    market_spec: DictConfig,
    bookmaker_cfg: DictConfig,
) -> pd.Series:
    """Единая точка входа для тренера: ``odds_raw`` или ``odds_transport: wide_columns``.

    Args:
        df: Test frame с passthrough колонками.
        market_spec: Рынок.
        bookmaker_cfg: Профиль букмекера (fonbet / the_odds_api / др.).

    Returns:
        Series коэффициентов в decimal для стороны ставки (long — по строке).
    """
    transport = bookmaker_cfg.get("odds_transport") or {}
    mode = transport.get("mode")
    if mode == "wide_columns":
        ser = _extract_odds_wide_transport(df, market_spec, transport)
        if ser.notna().any():
            valid = int(ser.notna().sum())
            logger.info(
                "extract_betting_odds: transport=wide_columns bookmaker=%s market=%s, %d/%d",
                bookmaker_cfg.get("name", "?"),
                market_spec.name,
                valid,
                len(df),
            )
            return ser
    return extract_odds_from_raw(df, market_spec, bookmaker_cfg)
