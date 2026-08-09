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

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    high_null_detail: str | None = None
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

        # Проверяем фичи с высоким % null (часто h2h / редкие контексты — ожидаемо)
        high_null = [c for c in f_cols if df[c].isnull().mean() > 0.5]
        if high_null:
            high_null_detail = (
                f"Фичи с >50% null ({len(high_null)}): "
                f"{high_null[:5]}{'...' if len(high_null) > 5 else ''}"
            )
            warnings.append(high_null_detail)

    result.warnings = warnings
    for w in warnings:
        if w is high_null_detail:
            logger.debug("  %s", w)
        else:
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
    latest_mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    now = datetime.now(tz=UTC)
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
    """Хук Airflow: заглушка до подключения чтения метрик из MLflow (или аналога).

    Аргументы совпадают с контрактом DAG; пороги не применяются, пока нет backend метрик.

    Args:
        min_accuracy: Нижняя граница accuracy (планируется после реализации).
        max_ece: Верхняя граница ECE (планируется после реализации).

    Returns:
        Всегда ``True``, чтобы DAG мониторинга не падал на незаполненной проверке.
    """
    logger.info(
        "check_model_quality (stub): min_accuracy=%.2f, max_ece=%.2f",
        min_accuracy,
        max_ece,
    )
    logger.info("Проверки MLflow/Evidently не реализованы; возвращаю OK")
    return True


# Schema drift detection

_SNAPSHOT_DIR = Path("data/.schema_snapshots")


@dataclass
class SchemaDriftResult:
    """Результат проверки schema drift.

    Attributes:
        has_drift: Обнаружен ли дрифт.
        added_columns: Новые столбцы, отсутствующие в snapshot.
        removed_columns: Столбцы из snapshot, отсутствующие в текущих данных.
        type_changes: Столбцы с изменённым типом.
        snapshot_path: Путь к файлу snapshot.
    """

    has_drift: bool = False
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    type_changes: dict[str, dict[str, str]] = field(default_factory=dict)
    snapshot_path: str = ""


def save_schema_snapshot(
    df: pd.DataFrame,
    stage: str,
    tournament: str,
    snapshot_dir: Path | None = None,
) -> Path:
    """Сохранить snapshot схемы DataFrame для будущего сравнения.

    Args:
        df: DataFrame для создания snapshot.
        stage: Этап pipeline (raw, interim, processed).
        tournament: Название турнира.
        snapshot_dir: Директория для сохранения. По умолчанию data/.schema_snapshots.

    Returns:
        Путь к сохранённому snapshot.
    """
    out_dir = snapshot_dir or _SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "stage": stage,
        "tournament": tournament,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "columns": {
            col: {
                "dtype": str(df[col].dtype),
                "null_pct": round(float(df[col].isnull().mean() * 100), 2),
                "n_unique": int(df[col].nunique()),
            }
            for col in sorted(df.columns)
        },
    }

    filename = f"{stage}__{tournament}.json"
    path = out_dir / filename
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("📸 Schema snapshot сохранён: %s", path)
    return path


def check_schema_drift(
    df: pd.DataFrame,
    stage: str,
    tournament: str,
    snapshot_dir: Path | None = None,
) -> SchemaDriftResult:
    """Сравнить текущую схему DataFrame с сохранённым snapshot.

    Args:
        df: Текущий DataFrame.
        stage: Этап pipeline.
        tournament: Название турнира.
        snapshot_dir: Директория со snapshots.

    Returns:
        SchemaDriftResult с информацией о дрифте.
    """
    snap_dir = snapshot_dir or _SNAPSHOT_DIR
    filename = f"{stage}__{tournament}.json"
    snap_path = snap_dir / filename

    result = SchemaDriftResult(snapshot_path=str(snap_path))

    if not snap_path.exists():
        logger.info(
            "📋 Snapshot не найден для [%s / %s] — создаём первый",
            stage,
            tournament,
        )
        save_schema_snapshot(df, stage, tournament, snap_dir)
        return result

    # Загружаем snapshot
    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    saved_columns = set(snapshot.get("columns", {}).keys())
    current_columns = set(df.columns)

    # Новые столбцы
    result.added_columns = sorted(current_columns - saved_columns)

    # Удалённые столбцы
    result.removed_columns = sorted(saved_columns - current_columns)

    # Изменения типов
    for col in sorted(saved_columns & current_columns):
        saved_dtype = snapshot["columns"][col]["dtype"]
        current_dtype = str(df[col].dtype)
        if saved_dtype != current_dtype:
            result.type_changes[col] = {
                "was": saved_dtype,
                "now": current_dtype,
            }

    result.has_drift = bool(result.added_columns or result.removed_columns or result.type_changes)

    if result.has_drift:
        logger.warning("⚠ Schema drift обнаружен [%s / %s]:", stage, tournament)
        if result.added_columns:
            logger.warning("  + Новые столбцы: %s", result.added_columns)
        if result.removed_columns:
            logger.warning("  - Удалённые столбцы: %s", result.removed_columns)
        if result.type_changes:
            for col, change in result.type_changes.items():
                logger.warning("  ~ Тип изменён: %s (%s → %s)", col, change["was"], change["now"])
    else:
        logger.info("✓ Schema drift [%s / %s]: нет изменений", stage, tournament)

    return result


def report_duplicate_ids(
    df: pd.DataFrame,
    stage: str,
    tournament: str,
    id_column: str = "id",
) -> dict[str, Any]:
    """Отчёт о дублях ID в данных.

    Args:
        df: DataFrame для анализа.
        stage: Этап pipeline.
        tournament: Название турнира.
        id_column: Имя столбца с идентификатором.

    Returns:
        Словарь с информацией о дублях.
    """
    if id_column not in df.columns:
        logger.warning("Столбец '%s' не найден в [%s / %s]", id_column, stage, tournament)
        return {"error": f"column '{id_column}' not found"}

    total_rows = len(df)
    unique_ids = df[id_column].nunique()
    duplicated_mask = df.duplicated(subset=[id_column], keep=False)
    n_duplicated_rows = int(duplicated_mask.sum())
    n_duplicated_ids = int(df[duplicated_mask][id_column].nunique()) if n_duplicated_rows else 0

    report: dict[str, Any] = {
        "stage": stage,
        "tournament": tournament,
        "total_rows": total_rows,
        "unique_ids": unique_ids,
        "duplicated_rows": n_duplicated_rows,
        "duplicated_ids": n_duplicated_ids,
        "duplicate_pct": round(n_duplicated_rows / total_rows * 100, 2) if total_rows else 0,
    }

    if n_duplicated_ids > 0:
        # Топ-5 дублей
        dup_counts = df[duplicated_mask][id_column].value_counts().head(5).to_dict()
        report["top_duplicates"] = dup_counts

        logger.warning(
            "⚠ Дубли ID [%s / %s]: %d строк (%d уникальных ID), %.1f%%",
            stage,
            tournament,
            n_duplicated_rows,
            n_duplicated_ids,
            report["duplicate_pct"],
        )
        for dup_id, count in dup_counts.items():
            logger.warning("  → ID '%s': %d записей", dup_id, count)
    else:
        logger.info(
            "✓ Дубли ID [%s / %s]: нет (%d уникальных из %d строк)",
            stage,
            tournament,
            unique_ids,
            total_rows,
        )

    return report
