"""
Тесты для sports_forecast/predict.py — инференс модели.

Покрывает:
    - load_inference_dataset
    - load_model_from_path
    - load_feature_names
    - get_model_dir
    - find_model_file
    - get_available_tournaments
    - predict_single
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from omegaconf import DictConfig, OmegaConf

from sports_forecast.predict import (
    find_model_file,
    get_available_tournaments,
    get_model_dir,
    load_feature_names,
    load_inference_dataset,
    load_model_from_path,
    predict_single,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Небольшой DataFrame для тестов."""
    return pd.DataFrame(
        {
            "f_score_home": [1.0, 2.0, 3.0],
            "f_score_away": [0.5, 1.5, 2.5],
            "match_id": [101, 102, 103],
        }
    )


@pytest.fixture
def sample_cfg() -> DictConfig:
    """Минимальный конфиг для predict."""
    return OmegaConf.create(
        {
            "tournament": {"name": "uel_kz_1"},
            "market_spec": {"name": "total_over", "data_format": "wide"},
            "algorithm": {
                "name": "catboost",
                "_target_": "sports_forecast.training.models.catboost.CatBoostModel",
            },
            "features": {"name": "basic"},
            "paths": {
                "processed_dir": "data/processed",
                "predictions_dir": "data/predictions",
                "models_dir": "models",
            },
            "logging": {"level": "WARNING"},
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# load_inference_dataset
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadInferenceDataset:
    """Тесты для load_inference_dataset."""

    def test_loads_parquet_file(self, tmp_path: Path, sample_df: pd.DataFrame) -> None:
        """Успешная загрузка parquet файла."""
        tournament_dir = tmp_path / "uel_kz_1"
        tournament_dir.mkdir()
        dataset_path = tournament_dir / "inference_wide.parquet"
        sample_df.to_parquet(dataset_path, index=False)

        result = load_inference_dataset(
            processed_root=tmp_path,
            tournament="uel_kz_1",
            filename="inference_wide.parquet",
        )
        assert result is not None
        assert len(result) == 3

    def test_returns_none_if_file_missing(self, tmp_path: Path) -> None:
        """Возвращает None если файл не найден."""
        result = load_inference_dataset(
            processed_root=tmp_path,
            tournament="nonexistent",
            filename="inference_wide.parquet",
        )
        assert result is None

    def test_returns_none_for_empty_dataset(self, tmp_path: Path) -> None:
        """Возвращает None если DataFrame пуст."""
        tournament_dir = tmp_path / "uel_kz_1"
        tournament_dir.mkdir()
        dataset_path = tournament_dir / "inference_wide.parquet"
        pd.DataFrame().to_parquet(dataset_path, index=False)

        result = load_inference_dataset(
            processed_root=tmp_path,
            tournament="uel_kz_1",
            filename="inference_wide.parquet",
        )
        assert result is None

    def test_missing_feature_columns(self, tmp_path: Path, sample_df: pd.DataFrame) -> None:
        """Возвращает None если указанные фичи отсутствуют."""
        tournament_dir = tmp_path / "uel_kz_1"
        tournament_dir.mkdir()
        dataset_path = tournament_dir / "inference_wide.parquet"
        sample_df.to_parquet(dataset_path, index=False)

        result = load_inference_dataset(
            processed_root=tmp_path,
            tournament="uel_kz_1",
            filename="inference_wide.parquet",
            feature_columns=["nonexistent_col"],
        )
        assert result is None

    def test_valid_feature_columns(self, tmp_path: Path, sample_df: pd.DataFrame) -> None:
        """Успешно загружает если фичи присутствуют."""
        tournament_dir = tmp_path / "uel_kz_1"
        tournament_dir.mkdir()
        dataset_path = tournament_dir / "inference_wide.parquet"
        sample_df.to_parquet(dataset_path, index=False)

        result = load_inference_dataset(
            processed_root=tmp_path,
            tournament="uel_kz_1",
            filename="inference_wide.parquet",
            feature_columns=["f_score_home", "f_score_away"],
        )
        assert result is not None
        assert len(result) == 3


# ─────────────────────────────────────────────────────────────────────────────
# load_model_from_path
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadModelFromPath:
    """Тесты для load_model_from_path."""

    def test_raises_if_model_file_missing(self) -> None:
        """Вызывает FileNotFoundError если файл не найден."""
        cfg = OmegaConf.create(
            {
                "name": "catboost",
                "_target_": "sports_forecast.training.models.catboost.CatBoostModel",
            }
        )
        with pytest.raises(FileNotFoundError, match="Файл модели не найден"):
            load_model_from_path(cfg, Path("/nonexistent/model.cbm"))

    @patch("sports_forecast.predict.ModelFactory")
    def test_loads_model_successfully(self, mock_factory: MagicMock, tmp_path: Path) -> None:
        """Успешно загружает модель через ModelFactory."""
        model_file = tmp_path / "model.cbm"
        model_file.touch()

        mock_model = MagicMock()
        mock_factory.create_model.return_value = mock_model

        cfg = OmegaConf.create(
            {
                "name": "catboost",
                "_target_": "sports_forecast.training.models.catboost.CatBoostModel",
            }
        )

        result = load_model_from_path(cfg, model_file)

        mock_factory.create_model.assert_called_once_with(cfg)
        mock_model.load.assert_called_once_with(model_file)
        assert result is mock_model


# ─────────────────────────────────────────────────────────────────────────────
# load_feature_names
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadFeatureNames:
    """Тесты для load_feature_names."""

    def test_loads_feature_names(self, tmp_path: Path) -> None:
        """Загружает список фичей из features.txt."""
        features_path = tmp_path / "features.txt"
        features_path.write_text("f_score_home\nf_score_away\nf_form_5")

        result = load_feature_names(tmp_path)
        assert result == ["f_score_home", "f_score_away", "f_form_5"]

    def test_returns_none_if_file_missing(self, tmp_path: Path) -> None:
        """Возвращает None если features.txt не найден."""
        result = load_feature_names(tmp_path)
        assert result is None

    def test_handles_trailing_newlines(self, tmp_path: Path) -> None:
        """Корректно обрабатывает trailing newlines."""
        features_path = tmp_path / "features.txt"
        features_path.write_text("f_a\nf_b\n")

        result = load_feature_names(tmp_path)
        assert result == ["f_a", "f_b"]


# ─────────────────────────────────────────────────────────────────────────────
# get_model_dir
# ─────────────────────────────────────────────────────────────────────────────


class TestGetModelDir:
    """Тесты для get_model_dir."""

    def test_constructs_correct_path(self) -> None:
        """Формирует правильный путь к модели."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market_spec": {"name": "total_over"},
                "algorithm": {"name": "catboost"},
                "features": {"name": "basic"},
                "paths": {"models_dir": "models"},
            }
        )
        project_root = Path("/project")
        result = get_model_dir(cfg, project_root)

        expected = Path("/project/models/uel_kz_1/total_over/catboost_basic")
        assert result == expected

    def test_different_algorithm_featureset(self) -> None:
        """Разные алгоритмы/фичи → разные пути."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "lp_ru"},
                "market_spec": {"name": "winner"},
                "algorithm": {"name": "lgbm"},
                "features": {"name": "advanced"},
                "paths": {"models_dir": "models"},
            }
        )
        result = get_model_dir(cfg, Path("/proj"))
        assert result == Path("/proj/models/lp_ru/winner/lgbm_advanced")


# ─────────────────────────────────────────────────────────────────────────────
# find_model_file
# ─────────────────────────────────────────────────────────────────────────────


class TestFindModelFile:
    """Тесты для find_model_file."""

    def test_finds_cbm_file(self, tmp_path: Path) -> None:
        """Находит .cbm файл с версией prod."""
        model_file = tmp_path / "catboost_prod.cbm"
        model_file.touch()
        result = find_model_file(tmp_path, version="prod")
        assert result == model_file

    def test_finds_pkl_file(self, tmp_path: Path) -> None:
        """Находит .pkl файл с версией shadow."""
        model_file = tmp_path / "logreg_shadow.pkl"
        model_file.touch()
        result = find_model_file(tmp_path, version="shadow")
        assert result == model_file

    def test_finds_lgbm_file(self, tmp_path: Path) -> None:
        """Находит .lgbm файл."""
        model_file = tmp_path / "model_prod.lgbm"
        model_file.touch()
        result = find_model_file(tmp_path, version="prod")
        assert result == model_file

    def test_returns_none_if_no_model(self, tmp_path: Path) -> None:
        """Возвращает None если моделей нет."""
        result = find_model_file(tmp_path, version="prod")
        assert result is None

    def test_fallback_to_any_extension(self, tmp_path: Path) -> None:
        """Находит файл без суффикса версии (fallback)."""
        model_file = tmp_path / "model.cbm"
        model_file.touch()
        result = find_model_file(tmp_path, version="prod")
        # fallback finds it without version
        assert result == model_file

    def test_prefers_versioned_file(self, tmp_path: Path) -> None:
        """Предпочитает файл с суффиксом версии."""
        generic = tmp_path / "model.cbm"
        versioned = tmp_path / "model_prod.cbm"
        generic.touch()
        versioned.touch()
        result = find_model_file(tmp_path, version="prod")
        assert result == versioned


# ─────────────────────────────────────────────────────────────────────────────
# get_available_tournaments
# ─────────────────────────────────────────────────────────────────────────────


class TestGetAvailableTournaments:
    """Тесты для get_available_tournaments."""

    def test_returns_empty_if_dir_missing(self, tmp_path: Path) -> None:
        """Пустой список если директория не существует."""
        result = get_available_tournaments(tmp_path / "nonexistent")
        assert result == []

    def test_finds_tournaments_with_inference_files(self, tmp_path: Path) -> None:
        """Находит турниры с inference файлами."""
        t1 = tmp_path / "uel_kz_1"
        t1.mkdir()
        (t1 / "inference_wide.parquet").touch()

        t2 = tmp_path / "lp_ru"
        t2.mkdir()
        (t2 / "inference_long.parquet").touch()

        # Турнир без inference файла — не попадает
        t3 = tmp_path / "empty_tournament"
        t3.mkdir()

        result = get_available_tournaments(tmp_path)
        assert result == ["lp_ru", "uel_kz_1"]

    def test_ignores_non_directories(self, tmp_path: Path) -> None:
        """Игнорирует файлы, только директории."""
        (tmp_path / "random_file.txt").touch()
        result = get_available_tournaments(tmp_path)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# predict_single (integration-like)
# ─────────────────────────────────────────────────────────────────────────────


class TestPredictSingle:
    """Интеграционные тесты для predict_single."""

    @patch("sports_forecast.predict.load_model_from_path")
    def test_returns_false_if_no_model_file(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """Возвращает False если модель не найдена."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market_spec": {"name": "total_over", "data_format": "wide"},
                "algorithm": {"name": "catboost"},
                "features": {"name": "basic"},
                "paths": {
                    "processed_dir": "data/processed",
                    "predictions_dir": "data/predictions",
                    "models_dir": "models",
                },
            }
        )

        with patch("sports_forecast.predict.PROJECT_ROOT", tmp_path):
            result = predict_single(cfg, version="prod")

        assert result is False

    @patch("sports_forecast.predict.load_model_from_path")
    def test_full_pipeline_success(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """Полный цикл инференса — успех."""
        # Создаём директории
        processed = tmp_path / "data" / "processed" / "uel_kz_1"
        processed.mkdir(parents=True)

        model_dir = tmp_path / "models" / "uel_kz_1" / "total_over" / "catboost_basic"
        model_dir.mkdir(parents=True)

        predictions_dir = tmp_path / "data" / "predictions"
        predictions_dir.mkdir(parents=True)

        # Создаём inference датасет
        df = pd.DataFrame(
            {
                "f_score_home": np.random.rand(10),
                "f_score_away": np.random.rand(10),
                "match_id": range(10),
            }
        )
        df.to_parquet(processed / "inference_wide.parquet", index=False)

        # Создаём features.txt
        (model_dir / "features.txt").write_text("f_score_home\nf_score_away")

        # Создаём файл модели
        (model_dir / "catboost_prod.cbm").touch()

        # Mock модели
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.column_stack(
            [np.full(10, 0.3), np.full(10, 0.7)]
        )
        mock_load.return_value = mock_model

        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market_spec": {"name": "total_over", "data_format": "wide"},
                "algorithm": {"name": "catboost"},
                "features": {"name": "basic"},
                "paths": {
                    "processed_dir": "data/processed",
                    "predictions_dir": "data/predictions",
                    "models_dir": "models",
                },
            }
        )

        with patch("sports_forecast.predict.PROJECT_ROOT", tmp_path):
            result = predict_single(cfg, version="prod")

        assert result is True

        # Проверяем что предсказания сохранены
        out_path = predictions_dir / "uel_kz_1" / "total_over" / "predictions_prod.parquet"
        assert out_path.exists()

        result_df = pd.read_parquet(out_path)
        assert "proba_total_over" in result_df.columns
        assert len(result_df) == 10

    @patch("sports_forecast.predict.load_model_from_path")
    def test_returns_false_if_inference_data_missing(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """Возвращает False если inference данные не найдены."""
        model_dir = tmp_path / "models" / "uel_kz_1" / "total_over" / "catboost_basic"
        model_dir.mkdir(parents=True)
        (model_dir / "model_prod.cbm").touch()

        mock_model = MagicMock()
        mock_load.return_value = mock_model

        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market_spec": {"name": "total_over", "data_format": "wide"},
                "algorithm": {"name": "catboost"},
                "features": {"name": "basic"},
                "paths": {
                    "processed_dir": "data/processed",
                    "predictions_dir": "data/predictions",
                    "models_dir": "models",
                },
            }
        )

        with patch("sports_forecast.predict.PROJECT_ROOT", tmp_path):
            result = predict_single(cfg, version="prod")

        assert result is False
