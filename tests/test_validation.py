"""Тесты для Pandera-валидации данных (sports_forecast.validation)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pandera.errors
import pytest

from sports_forecast.validation.gates import (
    SchemaDriftResult,
    ValidationResult,
    check_schema_drift,
    report_duplicate_ids,
    save_schema_snapshot,
    validate_dataframe,
    validate_interim,
    validate_processed,
    validate_raw,
)
from sports_forecast.validation.schemas import (
    RawSchema,
    validate_odds_float_columns,
    validate_pinnacle_odds_float_columns,
)


# Fixtures


@pytest.fixture()
def raw_df() -> pd.DataFrame:
    """Минимальный корректный raw DataFrame."""
    return pd.DataFrame(
        {
            "id": ["m1", "m2", "m3"],
            "datetime": ["2026-01-01 10:00", "2026-01-01 11:00", "2026-01-01 12:00"],
            "status": ["end", "end", "upcoming"],
            "home_team": ["Player A", "Player B", "Player C"],
            "away_team": ["Player D", "Player E", "Player F"],
        }
    )


@pytest.fixture()
def interim_df() -> pd.DataFrame:
    """Минимальный корректный interim DataFrame."""
    return pd.DataFrame(
        {
            "id": [f"m{i}" for i in range(20)],
            "datetime": pd.date_range("2026-01-01", periods=20, freq="h"),
            "status": ["finished"] * 18 + ["upcoming"] * 2,
            "home_points": np.random.randint(0, 10, 20).astype(float),
            "away_points": np.random.randint(0, 10, 20).astype(float),
        }
    )


@pytest.fixture()
def processed_long_df() -> pd.DataFrame:
    """Минимальный корректный processed long DataFrame."""
    n_matches = 20
    rows = []
    for i in range(n_matches):
        for side in ["h", "a"]:
            rows.append(
                {
                    "id": f"m{i}",
                    "datetime": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=i),
                    "side": side,
                    "is_home": 1 if side == "h" else 0,
                    "pl_points": float(np.random.randint(0, 10)),
                    "opp_points": float(np.random.randint(0, 10)),
                    "f_ewm_10": np.random.randn(),
                    "f_count": float(np.random.randint(1, 100)),
                }
            )
    return pd.DataFrame(rows)


# Tests — Odds store (Pandera V1/V2, R20/R21)


class TestValidateOddsFloatColumnsV2:
    """R21.7: decimal + total_line + timing для V2, совместимость с V1."""

    def test_v2_positive_sample(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "pinnacle_winner_withOT_home_open": 1.91,
                    "pinnacle_winner_withOT_away_open": 2.05,
                    "pinnacle_winner_withOT_draw_open": None,
                    "pinnacle_winner_withOT_home_close": 1.9,
                    "pinnacle_winner_withOT_away_close": 2.1,
                    "pinnacle_winner_withOT_draw_close": None,
                    "pinnacle_total_withOT_line_open": 5.5,
                    "pinnacle_total_withOT_over_open": 1.95,
                    "pinnacle_total_withOT_under_open": 1.95,
                    "pinnacle_total_withOT_line_close": 5.5,
                    "pinnacle_total_withOT_over_close": 1.94,
                    "pinnacle_total_withOT_under_close": 1.96,
                    "onexbet_winner_home_close": 1.88,
                    "onexbet_winner_away_close": 2.2,
                    "onexbet_winner_draw_close": 4.0,
                    "onexbet_total_line_close": 5.0,
                    "onexbet_total_over_close": 1.9,
                    "onexbet_total_under_close": 1.92,
                    "open_minutes_before": 3000.0,
                    "close_minutes_before": 120.0,
                }
            ]
        )
        validate_odds_float_columns(df, context="test_v2_ok")
        validate_pinnacle_odds_float_columns(df, context="alias_ok")

    def test_rejects_decimal_below_min(self) -> None:
        df = pd.DataFrame([{"pinnacle_winner_withOT_home_close": 1.0}])
        with pytest.raises(RuntimeError, match="test_bad_dec"):
            validate_odds_float_columns(df, context="test_bad_dec")

    def test_rejects_total_line_below_range(self) -> None:
        df = pd.DataFrame([{"pinnacle_total_withOT_line_open": 0.4}])
        with pytest.raises(RuntimeError, match="test_bad_line"):
            validate_odds_float_columns(df, context="test_bad_line")

    def test_rejects_total_line_above_range(self) -> None:
        df = pd.DataFrame([{"onexbet_total_line_open": 25.0}])
        with pytest.raises(RuntimeError, match="test_bad_line_hi"):
            validate_odds_float_columns(df, context="test_bad_line_hi")

    def test_rejects_negative_minutes(self) -> None:
        df = pd.DataFrame([{"open_minutes_before": -1.0}])
        with pytest.raises(RuntimeError, match="test_bad_time"):
            validate_odds_float_columns(df, context="test_bad_time")

    def test_rejects_negative_close_minutes(self) -> None:
        df = pd.DataFrame([{"close_minutes_before": -0.01}])
        with pytest.raises(RuntimeError, match="test_bad_close_m"):
            validate_odds_float_columns(df, context="test_bad_close_m")

    def test_v1_column_still_validated(self) -> None:
        good = pd.DataFrame([{"pinnacle_home_close": 2.0}])
        validate_odds_float_columns(good, context="v1")
        bad = pd.DataFrame([{"pinnacle_total_open": 1.0}])
        with pytest.raises(RuntimeError, match="v1bad"):
            validate_odds_float_columns(bad, context="v1bad")


class TestValidateOddsFloatColumnsV3:
    """R21.14: close-only store V3 — decimal + *_line_close + close_minutes_before."""

    def test_v3_positive_sample(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "pinnacle_winner_withOT_home_close": 1.91,
                    "pinnacle_winner_withOT_away_close": 2.05,
                    "pinnacle_total_withOT_line_close": 5.5,
                    "pinnacle_total_withOT_over_close": 1.95,
                    "pinnacle_total_withOT_under_close": 1.95,
                    "onexbet_winner_home_close": 1.88,
                    "onexbet_winner_away_close": 2.2,
                    "onexbet_winner_draw_close": 4.0,
                    "onexbet_total_line_close": 5.0,
                    "onexbet_total_over_close": 1.9,
                    "onexbet_total_under_close": 1.92,
                    "close_minutes_before": 15.0,
                }
            ]
        )
        validate_odds_float_columns(df, context="test_v3_ok")


# Tests — Raw Schema


class TestRawSchema:
    """Тесты валидации raw-данных."""

    def test_valid_raw(self, raw_df: pd.DataFrame) -> None:
        result = validate_raw(raw_df, tournament="test", raise_on_error=False)
        assert result.is_valid

    def test_missing_id_column(self, raw_df: pd.DataFrame) -> None:
        df = raw_df.drop(columns=["id"])
        result = validate_raw(df, tournament="test", raise_on_error=False)
        assert not result.is_valid

    def test_duplicate_ids_allowed(self, raw_df: pd.DataFrame) -> None:
        """Raw-данные допускают дублирующиеся id (до split на подтурниры)."""
        df = raw_df.copy()
        df.loc[1, "id"] = df.loc[0, "id"]
        result = validate_raw(df, tournament="test", raise_on_error=False)
        assert result.is_valid

    def test_null_ids(self, raw_df: pd.DataFrame) -> None:
        df = raw_df.copy()
        df.loc[0, "id"] = None
        result = validate_raw(df, tournament="test", raise_on_error=False)
        assert not result.is_valid


# Tests — Interim Schema


class TestInterimSchema:
    """Тесты валидации interim-данных."""

    def test_valid_interim(self, interim_df: pd.DataFrame) -> None:
        result = validate_interim(interim_df, tournament="test", raise_on_error=False)
        assert result.is_valid

    def test_negative_points(self, interim_df: pd.DataFrame) -> None:
        df = interim_df.copy()
        df.loc[0, "home_points"] = -5.0
        result = validate_interim(df, tournament="test", raise_on_error=False)
        assert not result.is_valid

    def test_too_few_rows(self) -> None:
        df = pd.DataFrame(
            {
                "id": ["m1"],
                "datetime": [pd.Timestamp("2026-01-01")],
                "status": ["finished"],
                "home_points": [5.0],
                "away_points": [3.0],
            }
        )
        result = validate_interim(df, tournament="test", raise_on_error=False)
        assert not result.is_valid

    def test_datetime_warnings(self, interim_df: pd.DataFrame) -> None:
        """Проверяет предупреждения о подозрительных датах."""
        df = interim_df.copy()
        df.loc[0, "datetime"] = pd.Timestamp("2015-01-01")
        result = validate_interim(df, tournament="test", raise_on_error=False)
        assert result.is_valid  # Warning, не ошибка
        assert len(result.warnings) > 0


# Tests — Processed Long Schema


class TestProcessedLongSchema:
    """Тесты валидации processed long-данных."""

    def test_valid_processed(self, processed_long_df: pd.DataFrame) -> None:
        result = validate_processed(
            processed_long_df, data_format="long", tournament="test", raise_on_error=False
        )
        assert result.is_valid

    def test_invalid_side(self, processed_long_df: pd.DataFrame) -> None:
        df = processed_long_df.copy()
        df.loc[0, "side"] = "x"
        result = validate_processed(df, data_format="long", tournament="test", raise_on_error=False)
        assert not result.is_valid

    def test_invalid_is_home(self, processed_long_df: pd.DataFrame) -> None:
        df = processed_long_df.copy()
        df.loc[0, "is_home"] = 2
        result = validate_processed(df, data_format="long", tournament="test", raise_on_error=False)
        assert not result.is_valid

    def test_no_features_warning(self) -> None:
        """Предупреждение если нет f_ столбцов."""
        df = pd.DataFrame(
            {
                "id": [f"m{i // 2}" for i in range(20)],
                "datetime": [
                    pd.Timestamp("2026-01-01") + pd.Timedelta(hours=i // 2) for i in range(20)
                ],
                "side": ["h", "a"] * 10,
                "is_home": [1, 0] * 10,
                "pl_points": np.random.rand(20) * 10,
                "opp_points": np.random.rand(20) * 10,
            }
        )
        result = validate_processed(df, data_format="long", tournament="test", raise_on_error=False)
        assert result.is_valid  # Warning, не ошибка
        assert any("f_" in w for w in result.warnings)


# Tests — ValidationResult


class TestValidationResult:
    """Тесты для ValidationResult dataclass."""

    def test_default_values(self) -> None:
        result = ValidationResult(is_valid=True, stage="test")
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []
        assert result.stats == {}

    def test_with_errors(self) -> None:
        result = ValidationResult(
            is_valid=False,
            stage="raw",
            errors=["missing column", "duplicate id"],
        )
        assert not result.is_valid
        assert len(result.errors) == 2


# Tests — Quality Gate functions


class TestQualityGates:
    """Тесты для функций Quality Gate."""

    def test_validate_dataframe_raise_on_error(self, raw_df: pd.DataFrame) -> None:
        """Проверяем что raise_on_error=True бросает исключение."""
        df = raw_df.drop(columns=["id"])
        with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
            validate_dataframe(df, RawSchema, stage="raw", raise_on_error=True)

    def test_validate_dataframe_no_raise(self, raw_df: pd.DataFrame) -> None:
        """Проверяем что raise_on_error=False возвращает результат без исключения."""
        df = raw_df.drop(columns=["id"])
        result = validate_dataframe(df, RawSchema, stage="raw", raise_on_error=False)
        assert not result.is_valid


# Tests — Schema Drift Detection


class TestSchemaDrift:
    """Тесты для обнаружения schema drift."""

    def test_save_and_check_no_drift(self, raw_df: pd.DataFrame, tmp_path: Path) -> None:
        """Сохранение snapshot и проверка — нет дрифта."""
        save_schema_snapshot(raw_df, "raw", "test_tournament", tmp_path)
        result = check_schema_drift(raw_df, "raw", "test_tournament", tmp_path)
        assert not result.has_drift
        assert result.added_columns == []
        assert result.removed_columns == []
        assert result.type_changes == {}

    def test_detect_added_column(self, raw_df: pd.DataFrame, tmp_path: Path) -> None:
        """Обнаружение добавленного столбца."""
        save_schema_snapshot(raw_df, "raw", "test_tournament", tmp_path)
        df_new = raw_df.copy()
        df_new["new_column"] = 42
        result = check_schema_drift(df_new, "raw", "test_tournament", tmp_path)
        assert result.has_drift
        assert "new_column" in result.added_columns

    def test_detect_removed_column(self, raw_df: pd.DataFrame, tmp_path: Path) -> None:
        """Обнаружение удалённого столбца."""
        save_schema_snapshot(raw_df, "raw", "test_tournament", tmp_path)
        df_new = raw_df.drop(columns=["status"])
        result = check_schema_drift(df_new, "raw", "test_tournament", tmp_path)
        assert result.has_drift
        assert "status" in result.removed_columns

    def test_detect_type_change(self, raw_df: pd.DataFrame, tmp_path: Path) -> None:
        """Обнаружение изменения типа столбца."""
        save_schema_snapshot(raw_df, "raw", "test_tournament", tmp_path)
        df_new = raw_df.copy()
        df_new["id"] = df_new["id"].astype(int, errors="ignore")
        # Принудительно меняем тип
        df_new["id"] = range(len(df_new))
        result = check_schema_drift(df_new, "raw", "test_tournament", tmp_path)
        assert result.has_drift
        assert "id" in result.type_changes

    def test_no_snapshot_creates_one(self, raw_df: pd.DataFrame, tmp_path: Path) -> None:
        """Если snapshot нет — создаётся новый, дрифта нет."""
        result = check_schema_drift(raw_df, "raw", "new_tournament", tmp_path)
        assert not result.has_drift
        assert (tmp_path / "raw__new_tournament.json").exists()

    def test_schema_drift_result_defaults(self) -> None:
        """Дефолтные значения SchemaDriftResult."""
        result = SchemaDriftResult()
        assert not result.has_drift
        assert result.added_columns == []
        assert result.removed_columns == []
        assert result.type_changes == {}


# Tests — Duplicate ID Reporting


class TestDuplicateIds:
    """Тесты для отчёта о дублях ID."""

    def test_no_duplicates(self, raw_df: pd.DataFrame) -> None:
        """Нет дублей — отчёт чистый."""
        report = report_duplicate_ids(raw_df, "raw", "test")
        assert report["duplicated_rows"] == 0
        assert report["duplicated_ids"] == 0

    def test_with_duplicates(self, raw_df: pd.DataFrame) -> None:
        """Есть дубли — отчёт содержит информацию."""
        df = pd.concat([raw_df, raw_df.head(1)], ignore_index=True)
        report = report_duplicate_ids(df, "raw", "test")
        assert report["duplicated_rows"] > 0
        assert report["duplicated_ids"] > 0
        assert "top_duplicates" in report

    def test_missing_id_column(self, raw_df: pd.DataFrame) -> None:
        """Если id столбец отсутствует — ошибка."""
        df = raw_df.drop(columns=["id"])
        report = report_duplicate_ids(df, "raw", "test", id_column="id")
        assert "error" in report

    def test_duplicate_pct(self) -> None:
        """Проверяем корректность вычисления процента дублей."""
        df = pd.DataFrame({"id": ["a", "a", "b", "c"]})
        report = report_duplicate_ids(df, "raw", "test")
        assert report["duplicated_rows"] == 2
        assert report["duplicated_ids"] == 1
        assert report["duplicate_pct"] == 50.0
