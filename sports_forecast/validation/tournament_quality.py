"""Турнир-нейтральная проверка полноты сохранённого source-снимка.

Модуль не читает файлы и не запрашивает провайдеров: оркестратор передаёт ему
нормализованные строки локального ``source.csv`` и сохранённого снимка расписания.
Так граница между получением данных и качеством данных остаётся проверяемой.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.gates import ValidationResult


logger = get_logger(__name__)


@dataclass(frozen=True)
class TournamentQualityGateConfig:
    """Правила quality gate одного турнира для нормализованных строк.

    Все поля в снимке расписания и ``source.csv`` должны быть приведены к
    указанным именам до вызова gate. Это не связывает проверку с API конкретного
    поставщика.
    """

    tournament: str
    schedule_window_hours: int
    required_result_fields: tuple[str, ...]
    match_duration_minutes: int = 0
    provider_grace_minutes: int = 0
    result_field_rules: dict[str, ResultFieldRule] = field(default_factory=dict)
    id_column: str = "id"
    datetime_column: str = "datetime"
    schedule_state_column: str = "game_state"
    schedule_finished_values: tuple[str, ...] = ("OFF",)
    schedule_snapshot_filename: str = "quality_gate_schedule.csv"
    schedule_coverage_filename: str = "quality_gate_schedule.coverage.json"
    source_finished_column: str = "match_is_end"
    source_finished_values: tuple[str, ...] = ("1", "true")


@dataclass(frozen=True)
class ResultFieldRule:
    """Профильное правило типа и домена итогового поля completed матча."""

    value_type: str
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: tuple[str, ...] = ()


def validate_tournament_quality_gate(
    *,
    source_rows: pd.DataFrame,
    schedule_rows: pd.DataFrame,
    config: TournamentQualityGateConfig,
    refreshed_at: datetime,
    last_completed_at: datetime | None,
    schedule_covered_until: datetime | None = None,
) -> ValidationResult:
    """Проверить полноту расписания и результаты завершённых матчей.

    ``last_completed_at`` — сохранённый до refresh watermark последней локальной
    завершённой игры. Если его нет, проверяются все завершённые записи снимка до
    момента refresh: это безопаснее, чем пропустить ранний результат.
    """
    refreshed_utc = _as_utc(refreshed_at)
    result = ValidationResult(
        is_valid=True,
        stage="tournament_quality_gate",
        tournament=config.tournament,
        n_rows=len(source_rows),
        n_cols=len(source_rows.columns),
    )
    invalid_rule_fields = [
        field_name
        for field_name in config.required_result_fields
        if field_name not in config.result_field_rules
    ]
    if invalid_rule_fields:
        result.errors.append(
            f"Для обязательных полей не заданы правила типа или домена: {invalid_rule_fields}"
        )
    required_schedule_columns = (
        config.id_column,
        config.datetime_column,
        config.schedule_state_column,
    )
    missing_schedule = _missing_columns(schedule_rows, required_schedule_columns)
    required_source_columns = (
        config.id_column,
        config.datetime_column,
        config.source_finished_column,
        *config.required_result_fields,
    )
    missing_source = _missing_columns(source_rows, required_source_columns)
    if missing_schedule:
        result.errors.append(f"Снимок расписания не содержит обязательные поля: {missing_schedule}")
    if missing_source:
        result.errors.append(f"source-снимок не содержит обязательные поля: {missing_source}")
    if result.errors:
        result.is_valid = False
        return result

    schedule = schedule_rows.copy()
    source = source_rows.copy()
    schedule["_timestamp"] = _parse_timestamps(schedule[config.datetime_column])
    source["_timestamp"] = _parse_timestamps(source[config.datetime_column])
    schedule["_id"] = _normalise_ids(schedule[config.id_column])
    source["_id"] = _normalise_ids(source[config.id_column])

    if schedule["_timestamp"].isna().any():
        result.errors.append("Снимок расписания содержит некорректную дату матча")
    if source["_timestamp"].isna().any():
        result.errors.append("source-снимок содержит некорректную дату матча")
    if schedule["_id"].eq("").any():
        result.errors.append("Снимок расписания содержит пустой идентификатор матча")
    if source["_id"].eq("").any():
        result.errors.append("source-снимок содержит пустой идентификатор матча")
    if result.errors:
        result.is_valid = False
        return result

    window_end = refreshed_utc + timedelta(hours=config.schedule_window_hours)
    if schedule_covered_until is None or _as_utc(schedule_covered_until) < window_end:
        result.errors.append("Снимок расписания не покрывает заданное окно прогноза")
    scheduled = schedule.loc[
        (schedule["_timestamp"] >= refreshed_utc) & (schedule["_timestamp"] <= window_end)
    ]
    completed_start = _as_utc(last_completed_at) if last_completed_at is not None else None
    completed = schedule.loc[
        schedule[config.schedule_state_column].map(
            lambda value: _normalise_value(value)
            in _normalised_set(config.schedule_finished_values)
        )
    ]
    completed = completed.loc[completed["_timestamp"] <= refreshed_utc]
    if completed_start is not None:
        completed = completed.loc[completed["_timestamp"] >= completed_start]

    duplicate_schedule_ids = scheduled.loc[scheduled["_id"].duplicated(keep=False), "_id"].nunique()
    if duplicate_schedule_ids:
        result.errors.append(f"Снимок расписания дублирует матчи в окне: {duplicate_schedule_ids}")
    duplicate_completed_ids = completed.loc[
        completed["_id"].duplicated(keep=False), "_id"
    ].nunique()
    if duplicate_completed_ids:
        result.errors.append(
            f"Снимок расписания дублирует завершённые матчи: {duplicate_completed_ids}"
        )
    _validate_schedule_presence(result, scheduled, source)
    _validate_completed_results(result, completed, source, config)
    result.stats = {
        "schedule_matches": len(scheduled),
        "completed_matches": len(completed),
    }
    result.is_valid = not result.errors
    if result.is_valid:
        logger.info(
            "Quality gate турнира %s пройден: расписание=%d, завершённые=%d",
            config.tournament,
            len(scheduled),
            len(completed),
        )
    else:
        logger.error(
            "Quality gate турнира %s не пройден: ошибок=%d",
            config.tournament,
            len(result.errors),
        )
    return result


def schedule_snapshot_path(source_csv_path: Path, config: TournamentQualityGateConfig) -> Path:
    """Вернуть путь сохранённого нормализованного снимка рядом с ``source.csv``."""
    filename = config.schedule_snapshot_filename.strip()
    if not filename or Path(filename).name != filename:
        raise ValueError("Имя файла snapshot должно быть именем без каталога")
    return source_csv_path.parent / filename


def schedule_coverage_path(source_csv_path: Path, config: TournamentQualityGateConfig) -> Path:
    """Вернуть путь metadata с верхней границей покрытия schedule snapshot."""
    filename = config.schedule_coverage_filename.strip()
    if not filename or Path(filename).name != filename:
        raise ValueError("Имя файла coverage должно быть именем без каталога")
    return source_csv_path.parent / filename


def save_schedule_snapshot(
    schedule_rows: pd.DataFrame,
    path: Path,
    config: TournamentQualityGateConfig,
    covered_until: datetime | None = None,
) -> None:
    """Атомарно сохранить только нормализованные поля расписания.

    В snapshot намеренно не попадают исходный HTTP-payload, команды или другие
    необязательные поля поставщика.
    """
    normalized = _normalise_schedule_snapshot(schedule_rows, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    normalized.to_csv(temporary_path, index=False)
    temporary_path.replace(path)
    if covered_until is not None:
        _save_schedule_coverage(
            schedule_coverage_path(path.with_name("source.csv"), config), covered_until
        )
    logger.info(
        "Сохранён schedule snapshot турнира %s: матчей=%d", config.tournament, len(normalized)
    )


def load_schedule_snapshot(path: Path, config: TournamentQualityGateConfig) -> pd.DataFrame:
    """Загрузить и повторно проверить нормализованный snapshot расписания."""
    if not path.is_file():
        raise FileNotFoundError(f"Schedule snapshot не найден: {path}")
    try:
        rows = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError) as exc:
        raise ValueError(f"Не удалось прочитать schedule snapshot: {path}") from exc
    return _normalise_schedule_snapshot(rows, config)


def load_schedule_coverage(source_csv_path: Path, config: TournamentQualityGateConfig) -> datetime:
    """Загрузить верхнюю границу, до которой provider запросил расписание."""
    path = schedule_coverage_path(source_csv_path, config)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        value = raw["covered_until"]
        if not isinstance(value, str):
            raise ValueError
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось прочитать coverage schedule snapshot") from exc


def _save_schedule_coverage(path: Path, covered_until: datetime) -> None:
    payload = {"covered_until": _as_utc(covered_until).isoformat().replace("+00:00", "Z")}
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(path)


def _normalise_schedule_snapshot(
    schedule_rows: pd.DataFrame, config: TournamentQualityGateConfig
) -> pd.DataFrame:
    columns = (
        config.id_column,
        config.datetime_column,
        config.schedule_state_column,
    )
    missing_columns = _missing_columns(schedule_rows, columns)
    if missing_columns:
        raise ValueError(f"Snapshot расписания не содержит обязательные поля: {missing_columns}")
    normalized = schedule_rows.loc[:, list(columns)].copy()
    normalized[config.id_column] = _normalise_ids(normalized[config.id_column])
    timestamps = _parse_timestamps(normalized[config.datetime_column])
    normalized[config.datetime_column] = timestamps.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    normalized[config.schedule_state_column] = (
        normalized[config.schedule_state_column].fillna("").astype(str).str.strip()
    )
    if normalized[config.id_column].eq("").any():
        raise ValueError("Snapshot расписания содержит пустой идентификатор матча")
    if timestamps.isna().any():
        raise ValueError("Snapshot расписания содержит некорректную дату матча")
    if normalized[config.schedule_state_column].eq("").any():
        raise ValueError("Snapshot расписания содержит пустой статус матча")
    if normalized[config.id_column].duplicated().any():
        raise ValueError("Snapshot расписания содержит дублирующийся идентификатор матча")
    return normalized


def _validate_schedule_presence(
    result: ValidationResult, scheduled: pd.DataFrame, source: pd.DataFrame
) -> None:
    expected_ids = set(scheduled["_id"])
    source_ids = source.loc[source["_id"].isin(expected_ids), "_id"]
    missing_ids = expected_ids - set(source_ids)
    duplicate_ids = set(source_ids[source_ids.duplicated(keep=False)])
    if missing_ids:
        result.errors.append(f"В source отсутствуют матчи расписания: {len(missing_ids)}")
    if duplicate_ids:
        result.errors.append(f"В source дублируются матчи расписания: {len(duplicate_ids)}")


def _validate_completed_results(
    result: ValidationResult,
    completed: pd.DataFrame,
    source: pd.DataFrame,
    config: TournamentQualityGateConfig,
) -> None:
    completed_ids = set(completed["_id"])
    source_by_id = source.loc[source["_id"].isin(completed_ids)].groupby("_id", sort=False)
    source_finished_values = _normalised_set(config.source_finished_values)
    for match_id in completed_ids:
        if match_id not in source_by_id.groups:
            result.errors.append("Завершённый матч из расписания отсутствует в source")
            continue
        rows = source_by_id.get_group(match_id)
        if len(rows) != 1:
            result.errors.append("Завершённый матч из расписания дублируется в source")
            continue
        row = rows.iloc[0]
        if _normalise_value(row[config.source_finished_column]) not in source_finished_values:
            result.errors.append("У завершённого матча отсутствует финальный статус")
            continue
        absent_fields = [field for field in config.required_result_fields if _is_empty(row[field])]
        if absent_fields:
            result.errors.append(
                f"У завершённого матча повреждены обязательные поля: {', '.join(absent_fields)}"
            )
            continue
        invalid_fields = [
            field_name
            for field_name in config.required_result_fields
            if not _matches_result_rule(row[field_name], config.result_field_rules[field_name])
        ]
        if invalid_fields:
            result.errors.append(
                f"У завершённого матча нарушен тип или домен поля: {', '.join(invalid_fields)}"
            )


def _missing_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> list[str]:
    return [column for column in columns if column not in df.columns]


def _parse_timestamps(values: pd.Series[Any]) -> pd.Series[Any]:
    return pd.to_datetime(values, errors="coerce", utc=True)


def _normalise_ids(values: pd.Series[Any]) -> pd.Series[str]:
    return values.fillna("").astype(str).str.strip()


def _normalise_value(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip().casefold()


def _normalised_set(values: tuple[str, ...]) -> set[str]:
    return {value.strip().casefold() for value in values}


def _is_empty(value: Any) -> bool:
    return pd.isna(value) or not str(value).strip()


def _matches_result_rule(value: Any, rule: ResultFieldRule) -> bool:
    """Проверить непустое итоговое значение против профильного правила."""
    if rule.value_type == "integer":
        try:
            numeric = float(str(value).strip())
        except ValueError:
            return False
        if not numeric.is_integer():
            return False
        return (rule.minimum is None or numeric >= rule.minimum) and (
            rule.maximum is None or numeric <= rule.maximum
        )
    if rule.value_type == "enum":
        return _normalise_value(value) in _normalised_set(rule.allowed_values)
    return False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
