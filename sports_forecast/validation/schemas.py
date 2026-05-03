"""Pandera-схемы для валидации данных на каждом слое pipeline.

Определяет строгие контракты данных для:
    - Raw:           после ingest (matches.parquet)
    - Interim:       после clean (matches_interim.parquet)
    - Processed Long: после features (train_long.parquet / inference_long.parquet)
    - Processed Wide: после features (train_wide.parquet / inference_wide.parquet)

Usage::

    from sports_forecast.validation.schemas import InterimSchema
    InterimSchema.validate(df)

    from sports_forecast.validation.schemas import validate_odds_float_columns
    validate_odds_float_columns(odds_df, context="backfill")
"""

from __future__ import annotations

from typing import Final

import pandas as pd
from pandera import Check, Column, DataFrameSchema
from pandera.errors import SchemaError, SchemaErrors

from sports_forecast.data.providers.odds.store import (
    ODDS_STORE_COLUMNS_V1,
    ODDS_STORE_COLUMNS_V2,
    ODDS_STORE_COLUMNS_V3,
)


# Метаданные store (не odds-числа)
_ODDS_STORE_NON_DECIMAL_V2: Final[frozenset[str]] = frozenset(
    {
        "game_date",
        "home_team_norm",
        "away_team_norm",
        "commence_time_utc",
        "open_snapshot_utc",
        "close_snapshot_utc",
        "open_minutes_before",
        "close_minutes_before",
        "fetched_at",
    }
)

# R21.10+ V3: close-only, без open
_ODDS_STORE_NON_DECIMAL_V3: Final[frozenset[str]] = frozenset(
    {
        "game_date",
        "home_team_norm",
        "away_team_norm",
        "commence_time_utc",
        "close_snapshot_utc",
        "close_minutes_before",
        "fetched_at",
    }
)

# R20 V1: только decimal-колонки Pinnacle
_PINNACLE_ODDS_FLOAT_COLS: tuple[str, ...] = tuple(
    c for c in ODDS_STORE_COLUMNS_V1 if c.startswith("pinnacle_")
)

# R21 V2: decimal (home/away/draw, over/under) без total_line
_ODDS_V2_DECIMAL_COLS: Final[tuple[str, ...]] = tuple(
    c for c in ODDS_STORE_COLUMNS_V2 if c not in _ODDS_STORE_NON_DECIMAL_V2 and "_line_" not in c
)
# R21: линия тотала (point)
_ODDS_V2_TOTAL_LINE_COLS: Final[tuple[str, ...]] = tuple(
    c for c in ODDS_STORE_COLUMNS_V2 if "_line_" in c
)

# R21 V3: только close-десятичные (без line / без метаданных)
_ODDS_V3_DECIMAL_COLS: Final[tuple[str, ...]] = tuple(
    c for c in ODDS_STORE_COLUMNS_V3 if c not in _ODDS_STORE_NON_DECIMAL_V3 and "_line_" not in c
)
_ODDS_V3_TOTAL_LINE_COLS: Final[tuple[str, ...]] = tuple(
    c for c in ODDS_STORE_COLUMNS_V3 if "_line_" in c
)

_ODDS_MINUTES_BEFORE_COLS: Final[tuple[str, ...]] = ("open_minutes_before", "close_minutes_before")

# Union V1 + V2 + V3 decimal (уникальные имена) — одна проверка диапазона
_ODDS_DECIMAL_COLS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys([*_PINNACLE_ODDS_FLOAT_COLS, *_ODDS_V2_DECIMAL_COLS, *_ODDS_V3_DECIMAL_COLS])
)


def _pinnacle_odds_in_valid_range(s: pd.Series) -> bool:
    """True, если все ненулевые значения в [1.01, 100.0]."""
    ok = s.isna() | ((s >= 1.01) & (s <= 100.0))
    return bool(ok.all()) if len(s) else True


def _odds_total_line_in_valid_range(s: pd.Series) -> bool:
    """True, если все ненулевые значения в [0.5, 20.0] (V2 total line / point)."""
    ok = s.isna() | ((s >= 0.5) & (s <= 20.0))
    return bool(ok.all()) if len(s) else True


def _odds_minutes_nonnegative(s: pd.Series) -> bool:
    """True, если ``open_minutes_before``/``close_minutes_before`` — null или >= 0."""
    ok = s.isna() | (s >= 0)
    return bool(ok.all()) if len(s) else True


# Колонка для Pandera: decimal odds (V1 + V2)
_OddsDecimalColumn = Column(
    dtype="float",
    nullable=True,
    checks=Check(
        _pinnacle_odds_in_valid_range,
        error="decimal odds must be in [1.01, 100.0] or null",
    ),
)

_OddsTotalLineColumn = Column(
    dtype="float",
    nullable=True,
    checks=Check(
        _odds_total_line_in_valid_range,
        error="total line must be in [0.5, 20.0] or null",
    ),
)

_OddsMinutesColumn = Column(
    dtype="float",
    nullable=True,
    checks=Check(
        _odds_minutes_nonnegative,
        error="minutes_before must be >= 0 or null",
    ),
)

# Публично: R20-совместимая схема только с V1-колонками (Pinnacle)
PinnacleOddsNumericSchema = DataFrameSchema(
    columns=dict.fromkeys(_PINNACLE_ODDS_FLOAT_COLS, _OddsDecimalColumn),
    strict=False,
    coerce=True,
    name="PinnacleOddsNumericSchema",
    description="Pinnacle decimal odds (R20 V1): nullable float, 1.01…100.0 (на NaN проверки нет).",
)


def _build_odds_store_checks_schema(
    have_decimal: list[str],
    have_line: list[str],
    have_minutes: list[str],
) -> DataFrameSchema:
    """Собрать схему по фактически присутствующим колонкам."""
    col_map: dict[str, Column] = {}
    for c in have_decimal:
        col_map[c] = _OddsDecimalColumn
    for c in have_line:
        col_map[c] = _OddsTotalLineColumn
    for c in have_minutes:
        col_map[c] = _OddsMinutesColumn
    return DataFrameSchema(
        col_map,
        strict=False,
        coerce=True,
        name="OddsStoreNumericV1V2V3",
        description="Odds store: decimal odds, total_line, minutes_before (V1/V2/V3 union, nullable).",
    )


def validate_odds_float_columns(
    df: pd.DataFrame,
    *,
    context: str = "odds",
) -> None:
    """Pandera-валидация odds-чисел для R20 (V1) и R21 (V2/V3): букмекеры Pinnacle/1xBet.

    Проверяет **только присутствующие** в ``df`` колонки:

    * decimal: ``pinnacle_home_open`` (V1) и/или V2 ``*_winner_*`` / ``*_over_*`` / ``*_under_*`` —
      диапазон [1.01, 100.0], nullable;
    * ``*_total_*_line_*`` (V2) и V3 ``*_line_close``: [0.5, 20.0], nullable;
    * ``open_minutes_before``, ``close_minutes_before`` — >= 0, nullable.

    Пустой ``df`` пропускается. Нет известных колонок — пропуск.

    Args:
        df: кадр из backfill/refresh/store.
        context: префикс :exc:`RuntimeError` (контекст).

    Raises:
        RuntimeError: обёртка вокруг :exc:`SchemaError` / :exc:`SchemaErrors`.
    """
    if df is None or df.empty:
        return
    have_dec = [c for c in _ODDS_DECIMAL_COLS if c in df.columns]
    have_line = [
        c for c in (*_ODDS_V2_TOTAL_LINE_COLS, *_ODDS_V3_TOTAL_LINE_COLS) if c in df.columns
    ]
    have_line = list(dict.fromkeys(have_line))
    have_min = [c for c in _ODDS_MINUTES_BEFORE_COLS if c in df.columns]
    if not have_dec and not have_line and not have_min:
        return
    sub = _build_odds_store_checks_schema(have_dec, have_line, have_min)
    cols = have_dec + have_line + have_min
    try:
        sub.validate(df[cols])
    except (SchemaError, SchemaErrors) as e:
        raise RuntimeError(f"{context}: {e!s}") from e


def validate_pinnacle_odds_float_columns(
    df: pd.DataFrame,
    *,
    context: str = "odds",
) -> None:
    """Обратная совместимость: то же, что :func:`validate_odds_float_columns`."""
    validate_odds_float_columns(df, context=context)


# ============================================================================
# RAW SCHEMA: после ingest (source CSV → parquet)
# ============================================================================
# Минимальный контракт: столбцы существуют и не пустые.
# На этапе raw все типы — object (строки из CSV).

RawSchema = DataFrameSchema(
    columns={
        "id": Column(
            dtype="object",
            nullable=False,
            # unique=False: до split на подтурниры id могут дублироваться
            description="Идентификатор матча (уникальность — после split)",
        ),
        "datetime": Column(
            dtype="object",
            nullable=False,
            description="Дата/время матча (строка, ещё не типизирована)",
        ),
        "status": Column(
            dtype="object",
            nullable=True,
            required=False,  # Не все source-форматы содержат status (e.g. table tennis)
            description="Статус матча (end, live, upcoming, ...)",
        ),
    },
    # Разрешаем дополнительные столбцы (raw данные имеют разную структуру)
    strict=False,
    coerce=False,
    name="RawSchema",
    description="Минимальная схема для raw-данных после ingest",
)


# ============================================================================
# INTERIM SCHEMA: после clean (raw → interim)
# ============================================================================
# После clean данные типизированы и стандартизированы.

InterimSchema = DataFrameSchema(
    columns={
        "id": Column(
            dtype="object",
            nullable=False,
            # unique=False: допускаем дубли (e.g. доп. раунды, OT в cyberhockey)
            description="Идентификатор матча",
        ),
        "datetime": Column(
            dtype="datetime64[ns]",
            nullable=False,
            description="Дата/время матча (типизировано)",
        ),
        "status": Column(
            dtype="object",
            nullable=True,
            description="Статус матча",
        ),
        "home_points": Column(
            dtype="float64",
            nullable=True,
            checks=[
                Check.ge(0, error="home_points не может быть отрицательным"),
                Check.le(100, error="home_points > 100 — подозрительно"),
            ],
            description="Очки домашней команды/игрока",
        ),
        "away_points": Column(
            dtype="float64",
            nullable=True,
            checks=[
                Check.ge(0, error="away_points не может быть отрицательным"),
                Check.le(100, error="away_points > 100 — подозрительно"),
            ],
            description="Очки гостевой команды/игрока",
        ),
        "home_goals_reg": Column(
            dtype="float64",
            nullable=True,
            required=False,
            checks=[
                Check.ge(0, error="home_goals_reg не может быть отрицательным"),
                Check.le(50, error="home_goals_reg > 50 — подозрительно"),
            ],
            description="NHL: голы дома в регламенте (периоды 1–3), из home_score_mt",
        ),
        "away_goals_reg": Column(
            dtype="float64",
            nullable=True,
            required=False,
            checks=[
                Check.ge(0, error="away_goals_reg не может быть отрицательным"),
                Check.le(50, error="away_goals_reg > 50 — подозрительно"),
            ],
            description="NHL: голы гостей в регламенте, из away_score_mt",
        ),
        "home_goals_full": Column(
            dtype="float64",
            nullable=True,
            required=False,
            checks=[
                Check.ge(0, error="home_goals_full не может быть отрицательным"),
                Check.le(50, error="home_goals_full > 50 — подозрительно"),
            ],
            description="NHL: финальные голы дома (регламент+ОТ/БУ), алиас к финальному счёту",
        ),
        "away_goals_full": Column(
            dtype="float64",
            nullable=True,
            required=False,
            checks=[
                Check.ge(0, error="away_goals_full не может быть отрицательным"),
                Check.le(50, error="away_goals_full > 50 — подозрительно"),
            ],
            description="NHL: финальные голы гостей (регламент+ОТ/БУ)",
        ),
        # --- NHL / ice_hockey (опционально; strict=False всё равно разрешает прочие колонки) ---
        "season": Column(
            dtype="object",
            nullable=True,
            required=False,
            description="Сезон NHL (строка из source)",
        ),
        "game_type": Column(
            dtype="object",
            nullable=True,
            required=False,
            description="Тип игры: regular / playoffs / preseason",
        ),
        "home_sog_ft": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Броски в створ (дома), полный матч",
        ),
        "away_sog_ft": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Броски в створ (гости), полный матч",
        ),
        "home_P": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Очки в таблице (дома)",
        ),
        "away_P": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Очки в таблице (гости)",
        ),
        "home_GP": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Сыграно игр (дома)",
        ),
        "away_GP": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Сыграно игр (гости)",
        ),
        "home_conference_standing": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Место в конференции (дома)",
        ),
        "away_conference_standing": Column(
            dtype="float64",
            nullable=True,
            required=False,
            description="Место в конференции (гости)",
        ),
    },
    # Разрешаем дополнительные столбцы (player names, tour_num, odds_raw, etc.)
    strict=False,
    coerce=False,
    name="InterimSchema",
    description="Схема для interim-данных после clean",
    checks=[
        # Общее: хотя бы 10 строк
        Check(lambda df: len(df) >= 10, error="Датасет содержит менее 10 строк"),
    ],
)


# ============================================================================
# PROCESSED LONG SCHEMA: после features (interim → processed)
# ============================================================================
# Long format: одна строка = один игрок в одном матче.

ProcessedLongSchema = DataFrameSchema(
    columns={
        "id": Column(
            dtype="object",
            nullable=False,
            description="Идентификатор матча (дублируется для h/a)",
        ),
        "datetime": Column(
            dtype="datetime64[ns]",
            nullable=False,
            description="Дата/время матча",
        ),
        "side": Column(
            dtype="object",
            nullable=False,
            checks=Check.isin(["h", "a"], error="side должен быть 'h' или 'a'"),
            description="Сторона: h (home) / a (away)",
        ),
        "is_home": Column(
            dtype="int64",
            nullable=False,
            checks=Check.isin([0, 1], error="is_home должен быть 0 или 1"),
            description="Флаг домашней стороны",
        ),
        "pl_points": Column(
            dtype="float64",
            nullable=True,
            checks=Check.ge(0, error="pl_points не может быть отрицательным"),
            description="Очки игрока",
        ),
        "opp_points": Column(
            dtype="float64",
            nullable=True,
            checks=Check.ge(0, error="opp_points не может быть отрицательным"),
            description="Очки оппонента",
        ),
    },
    strict=False,
    coerce=False,
    name="ProcessedLongSchema",
    description="Схема для processed long-данных (одна строка = игрок × матч)",
    checks=[
        # Каждый match_id должен иметь ровно 2 записи (h + a)
        Check(
            lambda df: df.groupby("id")["side"].nunique().eq(2).all()
            if "id" in df.columns
            else True,
            error="Каждый матч (id) должен иметь ровно 2 записи (h и a стороны)",
        ),
        # Проверяем что feature-столбцы не все NaN
        Check(
            lambda df: not df.filter(like="f_").isna().all(axis=None),
            error="Все feature-столбцы содержат NaN — возможно ошибка генерации",
            raise_warning=True,
        ),
    ],
)


# ============================================================================
# PROCESSED WIDE SCHEMA: после features (для тоталов)
# ============================================================================

ProcessedWideSchema = DataFrameSchema(
    columns={
        "id": Column(
            dtype="object",
            nullable=False,
            # unique=False: допускаем дубли (e.g. OT-матчи в cyberhockey)
            description="Идентификатор матча",
        ),
        "datetime": Column(
            dtype="datetime64[ns]",
            nullable=False,
            description="Дата/время матча",
        ),
        "home_points": Column(
            dtype="float64",
            nullable=True,
            checks=Check.ge(0, error="home_points не может быть отрицательным"),
        ),
        "away_points": Column(
            dtype="float64",
            nullable=True,
            checks=Check.ge(0, error="away_points не может быть отрицательным"),
        ),
    },
    strict=False,
    coerce=False,
    name="ProcessedWideSchema",
    description="Схема для processed wide-данных (одна строка = матч)",
    checks=[
        Check(lambda df: len(df) >= 10, error="Датасет содержит менее 10 строк"),
    ],
)


# ============================================================================
# INFERENCE SCHEMA: дополнительные проверки для inference-данных
# ============================================================================

InferenceLongSchema = ProcessedLongSchema.update_column(
    "pl_points",
    nullable=True,  # На inference нет результатов
)

InferenceWideSchema = ProcessedWideSchema.update_column(
    "home_points",
    nullable=True,  # На inference нет результатов
)


# ============================================================================
# PREDICTION SCHEMA: данные в Prediction Store
# ============================================================================

PredictionSchema = DataFrameSchema(
    columns={
        "match_id": Column(dtype="object", nullable=False),
        "tournament": Column(dtype="object", nullable=False),
        "market": Column(dtype="object", nullable=False),
        "market_spec": Column(dtype="object", nullable=False),
        "proba_home": Column(
            dtype="float64",
            nullable=True,
            checks=[
                Check.ge(0, error="proba_home < 0"),
                Check.le(1, error="proba_home > 1"),
            ],
        ),
        "proba_away": Column(
            dtype="float64",
            nullable=True,
            checks=[
                Check.ge(0, error="proba_away < 0"),
                Check.le(1, error="proba_away > 1"),
            ],
        ),
        "status": Column(
            dtype="object",
            nullable=False,
            checks=Check.isin(
                ["ok", "stale", "error", "not_ready"],
                error="Невалидный статус предсказания",
            ),
        ),
    },
    strict=False,
    coerce=False,
    name="PredictionSchema",
    description="Схема для предсказаний в Prediction Store",
)
