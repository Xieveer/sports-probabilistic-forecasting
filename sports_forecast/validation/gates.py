"""Quality Gates — функции валидации данных на каждом этапе pipeline.

Каждый gate возвращает ``ValidationResult`` и может:
    - блокировать pipeline (raise) при критических ошибках
    - предупреждать (warn) при подозрительных, но некритичных паттернах
    - логировать статистику прохождения валидации

Usage::

    from sports_forecast.validation.gates import validate_dataframe
    from sports_forecast.validation.schemas import InterimSchema

    result = validate_dataframe(df, InterimSchema, stage="interim")
    if not result.is_valid:
        raise RuntimeError(f"Validation failed: {result.errors}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pandera import DataFrameSchema
from pandera.errors import SchemaError, SchemaErrors

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Результат валидации данных.

    Attributes:
        is_valid: Прошла ли валидация без ошибок.
        stage: Название этапа (raw, interim, processed).
        tournament: Название турнира (если применимо).
        n_rows: Количество строк в датасете.
        n_cols: Количество столбцов.
        errors: Список ошибок валидации.
        warnings: Список предупреждений.
        stats: Дополнительная статистика.
    """

    is_valid: bool
    stage: str
    tournament: str = ""
    n_rows: int = 0
    n_cols: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def validate_dataframe(
    df: pd.DataFrame,
    schema: DataFrameSchema,
    stage: str = "unknown",
    tournament: str = "",
    raise_on_error: bool = True,
) -> ValidationResult:
    """Валидировать DataFrame по Pandera-схеме.

    Args:
        df: DataFrame для валидации.
        schema: Pandera-схема.
        stage: Название этапа pipeline (для логирования).
        tournament: Название турнира.
        raise_on_error: Бросить исключение при ошибке.

    Returns:
        ValidationResult с результатами валидации.

    Raises:
        pa.errors.SchemaErrors: Если raise_on_error=True и валидация не пройдена.
    """
    result = ValidationResult(
        is_valid=True,
        stage=stage,
        tournament=tournament,
        n_rows=len(df),
        n_cols=len(df.columns),
    )

    try:
        schema.validate(df, lazy=True)
        logger.info(
            "✓ Валидация [%s / %s]: OK (%d строк, %d столбцов)",
            stage,
            tournament or "all",
            len(df),
            len(df.columns),
        )

    except SchemaErrors as exc:
        result.is_valid = False
        for err_dict in exc.schema_errors:
            if isinstance(err_dict, dict):
                msg = str(err_dict.get("error", err_dict))
            else:
                msg = str(err_dict)
            result.errors.append(msg)

        logger.error(
            "✗ Валидация [%s / %s]: FAILED — %d ошибок",
            stage,
            tournament or "all",
            len(result.errors),
        )
        for err in result.errors:
            logger.error("  → %s", err)

        if raise_on_error:
            raise

    except SchemaError as exc:
        result.is_valid = False
        result.errors.append(str(exc))
        logger.error("✗ Валидация [%s / %s]: %s", stage, tournament, exc)
        if raise_on_error:
            raise

    # Дополнительная статистика
    result.stats = _compute_stats(df, stage)
    return result


def _compute_stats(df: pd.DataFrame, stage: str) -> dict[str, Any]:
    """Вычислить дополнительную статистику для отчёта.

    Args:
        df: Валидируемый DataFrame.
        stage: Этап pipeline.

    Returns:
        Словарь со статистикой.
    """
    stats: dict[str, Any] = {
        "null_pct": float(df.isnull().mean().mean() * 100),
        "duplicate_rows": int(df.duplicated().sum()),
    }

    # Для processed — считаем % null в фичах
    if stage in ("processed", "processed_long", "processed_wide"):
        f_cols = [c for c in df.columns if c.startswith("f_")]
        if f_cols:
            stats["feature_null_pct"] = float(df[f_cols].isnull().mean().mean() * 100)
            stats["n_features"] = len(f_cols)

    # Для interim — проверяем распределение статусов
    if "status" in df.columns:
        stats["status_counts"] = df["status"].value_counts().to_dict()

    return stats


def validate_raw(
    df: pd.DataFrame,
    tournament: str = "",
    raise_on_error: bool = True,
) -> ValidationResult:
    """Валидировать raw-данные после ingest.

    Args:
        df: Raw DataFrame (из matches.parquet).
        tournament: Название турнира.
        raise_on_error: Бросить исключение при ошибке.

    Returns:
        ValidationResult.
    """
    from sports_forecast.validation.schemas import RawSchema

    return validate_dataframe(
        df, RawSchema, stage="raw", tournament=tournament, raise_on_error=raise_on_error
    )


def validate_interim(
    df: pd.DataFrame,
    tournament: str = "",
    raise_on_error: bool = True,
) -> ValidationResult:
    """Валидировать interim-данные после clean.

    Args:
        df: Interim DataFrame (из matches_interim.parquet).
        tournament: Название турнира.
        raise_on_error: Бросить исключение при ошибке.

    Returns:
        ValidationResult.
    """
    from sports_forecast.validation.schemas import InterimSchema

    result = validate_dataframe(
        df, InterimSchema, stage="interim", tournament=tournament, raise_on_error=raise_on_error
    )

    # Дополнительные проверки
    warnings: list[str] = []

    # Проверка: datetime в разумном диапазоне
    if "datetime" in df.columns and pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        min_dt = df["datetime"].min()
        max_dt = df["datetime"].max()
        if min_dt.year < 2020:
            warnings.append(f"Минимальная дата {min_dt} раньше 2020 — проверьте данные")
        if max_dt.year > 2030:
            warnings.append(f"Максимальная дата {max_dt} позже 2030 — проверьте данные")

    # Проверка: соотношение null в points
    if "home_points" in df.columns:
        null_pct = df["home_points"].isnull().mean()
        if null_pct > 0.5:
            warnings.append(
                f"home_points содержит {null_pct:.0%} null — возможно много незавершённых матчей"
            )

    result.warnings = warnings
    for w in warnings:
        logger.warning("  ⚠ %s", w)

    return result


def validate_processed(
    df: pd.DataFrame,
    data_format: str = "long",
    tournament: str = "",
    raise_on_error: bool = True,
) -> ValidationResult:
    """Валидировать processed-данные после feature generation.

    Args:
        df: Processed DataFrame.
        data_format: Формат данных ('long' или 'wide').
        tournament: Название турнира.
        raise_on_error: Бросить исключение при ошибке.

    Returns:
        ValidationResult.
    """
    from sports_forecast.validation.schemas import ProcessedLongSchema, ProcessedWideSchema

    schema = ProcessedLongSchema if data_format == "long" else ProcessedWideSchema
    stage = f"processed_{data_format}"

    result = validate_dataframe(
        df, schema, stage=stage, tournament=tournament, raise_on_error=raise_on_error
    )

    # Дополнительные проверки фичей
    warnings: list[str] = []
    f_cols = [c for c in df.columns if c.startswith("f_")]

    if not f_cols:
        warnings.append("Нет столбцов с префиксом 'f_' — feature generation не выполнена?")
    else:
        # Проверяем константные фичи (нулевая дисперсия)
        const_features = [c for c in f_cols if df[c].nunique(dropna=False) <= 1]
        if const_features:
            warnings.append(
                f"Найдены константные фичи ({len(const_features)}): "
                f"{const_features[:5]}{'...' if len(const_features) > 5 else ''}"
            )

        # Проверяем фичи с высоким % null
        high_null = [c for c in f_cols if df[c].isnull().mean() > 0.5]
        if high_null:
            warnings.append(
                f"Фичи с >50% null ({len(high_null)}): "
                f"{high_null[:5]}{'...' if len(high_null) > 5 else ''}"
            )

    result.warnings = warnings
    for w in warnings:
        logger.warning("  ⚠ %s", w)

    return result


def check_data_freshness(
    max_hours: int = 12,
    data_dir: str = "data/processed",
) -> bool:
    """Проверить свежесть данных (для мониторинга).

    Args:
        max_hours: Максимальный возраст данных в часах.
        data_dir: Путь к директории processed данных.

    Returns:
        True если данные свежие, False если устарели.

    Raises:
        RuntimeError: Если данные старше max_hours (для Airflow fail).
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        msg = f"Директория с данными не найдена: {data_path}"
        logger.error(msg)
        raise RuntimeError(msg)

    # Находим самый свежий parquet-файл
    parquet_files = list(data_path.rglob("*.parquet"))
    if not parquet_files:
        msg = f"Не найдено parquet-файлов в {data_path}"
        logger.error(msg)
        raise RuntimeError(msg)

    latest = max(parquet_files, key=lambda p: p.stat().st_mtime)
    latest_mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    age = now - latest_mtime

    logger.info("Самый свежий файл: %s (возраст: %s)", latest.name, age)

    if age > timedelta(hours=max_hours):
        msg = f"Данные устарели: {latest.name} — возраст {age} > {max_hours}h"
        logger.warning(msg)
        raise RuntimeError(msg)

    logger.info("✓ Данные свежие (возраст: %s, лимит: %dh)", age, max_hours)
    return True


def check_model_quality(
    min_accuracy: float = 0.50,
    max_ece: float = 0.10,
) -> bool:
    """Проверить качество модели по последним MLflow метрикам (заглушка).

    В текущей версии — placeholder для будущей реализации
    с полноценной интеграцией Evidently / MLflow.

    Args:
        min_accuracy: Минимальный порог accuracy.
        max_ece: Максимальный допустимый ECE.

    Returns:
        True если качество в норме.
    """
    logger.info(
        "check_model_quality: min_accuracy=%.2f, max_ece=%.2f",
        min_accuracy,
        max_ece,
    )
    logger.info("⚠ Полноценная проверка качества модели — TODO (требует Evidently/MLflow)")
    logger.info("✓ Качество модели: OK (placeholder)")
    return True
