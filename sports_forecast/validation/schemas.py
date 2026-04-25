"""Pandera-схемы для валидации данных на каждом слое pipeline.

Определяет строгие контракты данных для:
    - Raw:           после ingest (matches.parquet)
    - Interim:       после clean (matches_interim.parquet)
    - Processed Long: после features (train_long.parquet / inference_long.parquet)
    - Processed Wide: после features (train_wide.parquet / inference_wide.parquet)

Usage::

    from sports_forecast.validation.schemas import InterimSchema
    InterimSchema.validate(df)

    from sports_forecast.validation.schemas import validate_pinnacle_odds_float_columns
    validate_pinnacle_odds_float_columns(odds_df, context="backfill")
"""

from __future__ import annotations

import pandas as pd
from pandera import Check, Column, DataFrameSchema
from pandera.errors import SchemaError, SchemaErrors


# Согласовано с :data:`sports_forecast.data.providers.odds.store.ODDS_STORE_COLUMNS` (только decimal).
_PINNACLE_ODDS_FLOAT_COLS: tuple[str, ...] = (
    "pinnacle_home_open",
    "pinnacle_away_open",
    "pinnacle_draw_open",
    "pinnacle_home_close",
    "pinnacle_away_close",
    "pinnacle_draw_close",
    "pinnacle_total_open",
    "pinnacle_total_close",
)


def _pinnacle_odds_in_valid_range(s: pd.Series) -> bool:
    """True, если все ненулевые значения в [1.01, 100.0]."""
    ok = s.isna() | ((s >= 1.01) & (s <= 100.0))
    return bool(ok.all()) if len(s) else True


PinnacleOddsNumericSchema = DataFrameSchema(
    columns={
        c: Column(
            dtype="float",
            nullable=True,
            checks=Check(
                _pinnacle_odds_in_valid_range,
                error=f"{c}: decimal odds must be in [1.01, 100.0] or null",
            ),
        )
        for c in _PINNACLE_ODDS_FLOAT_COLS
    },
    strict=False,
    coerce=True,
    name="PinnacleOddsNumericSchema",
    description="Pinnacle decimal odds: nullable float, 1.01…100.0 (на NaN проверки нет).",
)


def validate_pinnacle_odds_float_columns(
    df: pd.DataFrame,
    *,
    context: str = "odds",
) -> None:
    """Pandera-валидация колонок ``pinnacle_*`` (диапазон 1.01–100.0, nullable).

    Пустой ``df`` не валидируется. Резервные/отсутствующие колонки отбрасываются из проверки.

    Args:
        df: Кадр с возможными odds-колонками.
        context: Сообщение об ошибке (лог-контекст).

    Raises:
        SchemaError, SchemaErrors: Найдены ненулевые значения вне диапазона.
    """
    if df is None or df.empty:
        return
    have = [c for c in _PINNACLE_ODDS_FLOAT_COLS if c in df.columns]
    if not have:
        return
    sub = DataFrameSchema(
        {c: PinnacleOddsNumericSchema.columns[c] for c in have},
        strict=False,
        coerce=True,
    )
    try:
        sub.validate(df[have])
    except (SchemaError, SchemaErrors) as e:
        raise RuntimeError(f"{context}: {e!s}") from e


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
