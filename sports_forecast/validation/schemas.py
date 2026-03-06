"""Pandera-схемы для валидации данных на каждом слое pipeline.

Определяет строгие контракты данных для:
    - Raw:           после ingest (matches.parquet)
    - Interim:       после clean (matches_interim.parquet)
    - Processed Long: после features (train_long.parquet / inference_long.parquet)
    - Processed Wide: после features (train_wide.parquet / inference_wide.parquet)

Usage::

    from sports_forecast.validation.schemas import InterimSchema
    InterimSchema.validate(df)
"""

from __future__ import annotations

from pandera import Check, Column, DataFrameSchema


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
