"""
ModelTrainer - главный оркестратор обучения моделей.

Координирует:
- Загрузку данных
- Обучение моделей (одиночных и ансамблей)
- TSCV валидацию
- Optuna оптимизацию
- Калибровку
- Shadow/Prod сохранение
- MLflow логирование (Parent/Child runs)

Примеры:
    >>> trainer = ModelTrainer(cfg)
    >>> trainer.train_single("catboost", "uel_kz_1", use_optuna=True)
    >>> trainer.train_ensemble("stacking_win", "uel_kz_1")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.train import compute_expected_calibration_error, compute_target, select_features
from sports_forecast.training.calibration import ModelCalibrator
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.training.ensembles.stacking import StackingEnsemble
from sports_forecast.training.optimization.optuna_optimizer import OptunaOptimizer
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


class ModelTrainer:
    """
    Главный оркестратор обучения моделей.

    Управляет полным циклом обучения:
    1. Загрузка датасета и вычисление таргета
    2. Train/test split (90/10 по времени)
    3. TSCV на train (Shadow модель)
    4. Optuna оптимизация (опционально)
    5. Калибровка (опционально)
    6. Сохранение Shadow модели
    7. Дообучение на train+test (Prod модель)
    8. Сохранение Prod модели
    9. MLflow логирование (Parent/Child для ансамблей)

    Args:
        config: Hydra конфигурация проекта.
        project_root: Корневая директория проекта.

    Attributes:
        config: Конфигурация проекта.
        project_root: Корневая директория.

    Examples:
        >>> trainer = ModelTrainer(cfg, PROJECT_ROOT)
        >>> trainer.train_single("catboost", "uel_kz_1", use_optuna=True)
    """

    def __init__(self, config: DictConfig, project_root: Path):
        """
        Инициализация ModelTrainer.

        Args:
            config: Hydra конфигурация.
            project_root: Путь к корню проекта.
        """
        self.config = config
        self.project_root = project_root

        # Пути
        self.processed_root = project_root / config.paths.processed_dir
        self.models_root = project_root / config.paths.models_dir
        self.models_root.mkdir(parents=True, exist_ok=True)

        # MLflow
        mlflow_config = config.get("mlflow", {})
        tracking_uri = mlflow_config.get("tracking_uri", f"file:{project_root / 'mlruns'}")
        experiment_name = mlflow_config.get("experiment_name", "sports_forecast")

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)

        logger.info("ModelTrainer инициализирован")
        logger.info("  Processed data: %s", self.processed_root)
        logger.info("  Models: %s", self.models_root)
        logger.info("  MLflow: %s", tracking_uri)

    def load_dataset_and_target(
        self,
        tournament: str,
        model_config: DictConfig,
    ) -> tuple[pd.DataFrame, pd.Series, list[str]] | None:
        """
        Загрузить датасет и вычислить таргет.

        Args:
            tournament: Название турнира.
            model_config: Конфигурация модели.

        Returns:
            Tuple (X, y, feature_names) или None при ошибке.
        """
        # Определяем формат данных
        data_format = model_config.get("data_format", "long")
        dataset_filename = f"train_{data_format}.parquet"
        dataset_path = self.processed_root / tournament / dataset_filename

        if not dataset_path.exists():
            logger.error("Датасет не найден: %s", dataset_path)
            return None

        # Загружаем датасет
        logger.info("Загружаю датасет: %s", dataset_path)
        df = pd.read_parquet(dataset_path)
        logger.info("  Записей: %d, Колонок: %d", len(df), df.shape[1])

        # Загружаем конфиг турнира
        tournament_config_path = self.project_root / "conf" / "tournament" / f"{tournament}.yaml"
        tournament_cfg = OmegaConf.load(tournament_config_path)

        # Создаём полный конфиг (tournament + model)
        full_cfg = OmegaConf.create({
            "tournament": tournament_cfg,
            "model": model_config,
        })

        # Вычисляем таргет
        try:
            y = compute_target(df, full_cfg)
        except Exception as e:
            logger.error("Ошибка вычисления таргета: %s", e)
            return None

        # Отбираем фичи
        try:
            feature_names = select_features(df, model_config)
            X = df[feature_names]
        except Exception as e:
            logger.error("Ошибка отбора фичей: %s", e)
            return None

        logger.info("  Фичей: %d, Таргет: %s", len(feature_names), model_config.target_config.name)

        return X, y, feature_names

    def create_model(self, model_config: DictConfig) -> Any:
        """
        Создать экземпляр модели по конфигу.

        Args:
            model_config: Конфигурация модели.

        Returns:
            Экземпляр модели (BaseSingleModel или StackingEnsemble).

        Raises:
            ValueError: Если тип модели не поддерживается.
        """
        model_class_name = model_config.get("model_class", "")
        model_name = model_config.name

        # Маппинг классов
        model_classes = {
            "DummyModel": DummyModel,
            "CatBoostModel": CatBoostModel,
            "LGBMModel": LGBMModel,
            "LogRegModel": LogRegModel,
        }

        if model_class_name in model_classes:
            model_class = model_classes[model_class_name]
            return model_class(name=model_name, config=model_config)

        # Ансамбли
        if model_config.get("type") == "ensemble":
            ensemble_method = model_config.get("ensemble_method")
            if ensemble_method == "stacking":
                return self._create_stacking_ensemble(model_config)

        raise ValueError(f"Неизвестный тип модели: {model_class_name} (model: {model_name})")

    def _create_stacking_ensemble(self, ensemble_config: DictConfig) -> StackingEnsemble:
        """
        Создать Stacking Ensemble по конфигу.

        Args:
            ensemble_config: Конфигурация ансамбля.

        Returns:
            Экземпляр StackingEnsemble.
        """
        # Загружаем базовые модели
        base_models = []
        for base_model_path in ensemble_config.base_models:
            base_model_config_path = self.project_root / "conf" / "model" / f"{base_model_path}.yaml"
            base_model_config = OmegaConf.load(base_model_config_path)
            base_model = self.create_model(base_model_config)
            base_models.append(base_model)

        # Создаём мета-модель
        meta_model_config = ensemble_config.meta_model
        meta_model_type = meta_model_config.get("type", "logreg")

        if meta_model_type == "logreg":
            meta_model = LogRegModel(name="meta_logreg", params=dict(meta_model_config.params))
        else:
            raise ValueError(f"Неизвестный тип мета-модели: {meta_model_type}")

        # Создаём ансамбль
        return StackingEnsemble(
            name=ensemble_config.name,
            base_models=base_models,
            meta_model=meta_model,
            config=ensemble_config,
            n_splits=ensemble_config.get("tscv", {}).get("n_splits", 4),
        )

    def train_single(
        self,
        model_name: str,
        tournament: str,
        use_optuna: bool = False,
        use_calibration: bool = True,
    ) -> bool:
        """
        Обучить одиночную модель для турнира.

        Args:
            model_name: Название модели (catboost, lgbm, logreg, dummy).
            tournament: Название турнира.
            use_optuna: Использовать Optuna для оптимизации.
            use_calibration: Использовать калибровку.

        Returns:
            True если успешно, False иначе.

        Examples:
            >>> trainer.train_single("catboost", "uel_kz_1", use_optuna=True)
        """
        logger.info("=" * 60)
        logger.info("ОБУЧЕНИЕ ОДИНОЧНОЙ МОДЕЛИ")
        logger.info("Model: %s", model_name)
        logger.info("Tournament: %s", tournament)
        logger.info("=" * 60)

        # Загружаем конфиг модели
        model_config_path = self.project_root / "conf" / "model" / "single" / f"{model_name}.yaml"
        if not model_config_path.exists():
            logger.error("Конфиг модели не найден: %s", model_config_path)
            return False

        model_config = OmegaConf.load(model_config_path)

        # Загружаем датасет
        result = self.load_dataset_and_target(tournament, model_config)
        if result is None:
            return False

        X, y, feature_names = result

        # Train/test split (90/10 по времени)
        test_size = self.config.training.get("test_size", 0.1)
        split_idx = int(len(X) * (1 - test_size))

        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        logger.info("Split: train=%d (%.1f%%), test=%d (%.1f%%)",
                    len(X_train), (1 - test_size) * 100,
                    len(X_test), test_size * 100)

        # Создаём модель
        model = self.create_model(model_config)

        # Optuna оптимизация
        if use_optuna and model_config.get("optuna", {}).get("enabled", False):
            logger.info("--- OPTUNA ОПТИМИЗАЦИЯ ---")
            optimizer = OptunaOptimizer(model_name, tournament)
            best_params = optimizer.optimize(
                model=model,
                X_train=X_train,
                y_train=y_train,
                n_trials=model_config.optuna.get("n_trials", 30),
            )
            # Обновляем параметры модели
            model.params = best_params
            model.model_ = model._create_model()

        # TSCV для Shadow модели
        logger.info("--- TSCV (SHADOW МОДЕЛЬ) ---")
        tscv = TimeSeriesCrossValidator(n_splits=4)
        tscv_results = tscv.cross_validate(model, X_train, y_train)

        # Сохраняем Shadow модель (обучена на последнем фолде TSCV)
        shadow_path = self.models_root / tournament / model_name
        model.save(shadow_path, version="shadow")

        # Обучаем Prod модель (train + test)
        logger.info("--- PROD МОДЕЛЬ (train + test) ---")
        X_full = pd.concat([X_train, X_test])
        y_full = pd.concat([y_train, y_test])

        model.fit(X_full, y_full)

        # Калибровка (опционально)
        is_calibrated = False
        ece_before = None
        ece_after = None

        if use_calibration and model_config.get("calibration", {}).get("enabled", False):
            logger.info("--- КАЛИБРОВКА ---")
            calibrator = ModelCalibrator(
                threshold_ece=model_config.calibration.get("threshold_ece", 0.1),
                method=model_config.calibration.get("method", "isotonic"),
            )

            # Используем часть test для калибровки
            cal_size = int(len(X_test) * 0.5)
            X_cal = X_test.iloc[:cal_size]
            X_val = X_test.iloc[cal_size:]
            y_cal = y_test.iloc[:cal_size]
            y_val = y_test.iloc[cal_size:]

            model, is_calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
                model, X_cal, y_cal, X_val, y_val
            )

        # Сохраняем Prod модель
        prod_path = self.models_root / tournament / model_name
        model.save(prod_path, version="prod")

        # MLflow логирование
        self._log_to_mlflow_single(
            model_name=model_name,
            tournament=tournament,
            tscv_results=tscv_results,
            model_config=model_config,
            feature_names=feature_names,
            is_calibrated=is_calibrated,
            ece_before=ece_before,
            ece_after=ece_after,
        )

        logger.info("=" * 60)
        logger.info("✓ ОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 60)

        return True

    def _log_to_mlflow_single(
        self,
        model_name: str,
        tournament: str,
        tscv_results: dict,
        model_config: DictConfig,
        feature_names: list[str],
        is_calibrated: bool,
        ece_before: float | None,
        ece_after: float | None,
    ) -> None:
        """
        Логировать одиночную модель в MLflow.

        Args:
            model_name: Название модели.
            tournament: Название турнира.
            tscv_results: Результаты TSCV.
            model_config: Конфигурация модели.
            feature_names: Список фичей.
            is_calibrated: Была ли применена калибровка.
            ece_before: ECE до калибровки.
            ece_after: ECE после калибровки.
        """
        run_name = f"{tournament}_{model_name}"

        with mlflow.start_run(run_name=run_name):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", model_name)
            mlflow.set_tag("model_type", "single")

            # Параметры
            mlflow.log_param("n_features", len(feature_names))

            if hasattr(model_config, "params"):
                for key, value in model_config.params.items():
                    mlflow.log_param(f"model__{key}", value)

            # Shadow метрики (TSCV)
            for metric_name, value in tscv_results.items():
                if metric_name.startswith("mean_") or metric_name.startswith("std_"):
                    mlflow.log_metric(f"shadow_{metric_name}", value)
                elif metric_name.startswith("fold_"):
                    mlflow.log_metric(f"shadow_{metric_name}", value)

            # Калибровка
            if is_calibrated:
                mlflow.set_tag("calibrated", "true")
                if ece_before is not None:
                    mlflow.log_metric("ece_before_calibration", ece_before)
                if ece_after is not None:
                    mlflow.log_metric("ece_after_calibration", ece_after)
            else:
                mlflow.set_tag("calibrated", "false")

            # Фичи
            mlflow.log_text("\n".join(feature_names), "features.txt")

            logger.info("MLflow: run зарегистрирован")

    def train_ensemble(
        self,
        ensemble_name: str,
        tournament: str,
    ) -> bool:
        """
        Обучить ансамбль для турнира.

        Args:
            ensemble_name: Название ансамбля (stacking_win).
            tournament: Название турнира.

        Returns:
            True если успешно, False иначе.

        Examples:
            >>> trainer.train_ensemble("stacking_win", "uel_kz_1")
        """
        logger.info("=" * 60)
        logger.info("ОБУЧЕНИЕ АНСАМБЛЯ")
        logger.info("Ensemble: %s", ensemble_name)
        logger.info("Tournament: %s", tournament)
        logger.info("=" * 60)

        # Загружаем конфиг ансамбля
        ensemble_config_path = self.project_root / "conf" / "model" / "ensemble" / f"{ensemble_name}.yaml"
        if not ensemble_config_path.exists():
            logger.error("Конфиг ансамбля не найден: %s", ensemble_config_path)
            return False

        ensemble_config = OmegaConf.load(ensemble_config_path)

        # Загружаем датасет
        result = self.load_dataset_and_target(tournament, ensemble_config)
        if result is None:
            return False

        X, y, feature_names = result

        # Train/test split
        test_size = self.config.training.get("test_size", 0.1)
        split_idx = int(len(X) * (1 - test_size))

        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        # Создаём ансамбль
        ensemble = self._create_stacking_ensemble(ensemble_config)

        # Обучаем (TSCV для базовых + мета)
        ensemble.fit(X_train, y_train)

        # Сохраняем Shadow
        shadow_path = self.models_root / tournament / ensemble_name
        ensemble.save(shadow_path, version="shadow")

        # Обучаем Prod (train + test)
        X_full = pd.concat([X_train, X_test])
        y_full = pd.concat([y_train, y_test])

        ensemble.fit(X_full, y_full)

        # Сохраняем Prod
        prod_path = self.models_root / tournament / ensemble_name
        ensemble.save(prod_path, version="prod")

        logger.info("=" * 60)
        logger.info("✓ АНСАМБЛЬ ОБУЧЕН")
        logger.info("=" * 60)

        return True

    def train_all_tournaments(
        self,
        model_name: str,
        use_optuna: bool = False,
    ) -> dict[str, bool]:
        """
        Обучить модель для всех доступных турниров.

        Args:
            model_name: Название модели.
            use_optuna: Использовать Optuna.

        Returns:
            Словарь {tournament: success}.

        Examples:
            >>> results = trainer.train_all_tournaments("catboost", use_optuna=True)
        """
        # Получаем список турниров
        tournaments = self._get_available_tournaments()

        if not tournaments:
            logger.error("Нет доступных турниров")
            return {}

        logger.info("=" * 60)
        logger.info("МУЛЬТИТУРНИРНОЕ ОБУЧЕНИЕ")
        logger.info("Model: %s", model_name)
        logger.info("Tournaments: %d", len(tournaments))
        logger.info("=" * 60)

        results = {}
        for tournament in tournaments:
            success = self.train_single(model_name, tournament, use_optuna=use_optuna)
            results[tournament] = success

        # Статистика
        success_count = sum(results.values())
        logger.info("=" * 60)
        logger.info("ЗАВЕРШЕНО: %d/%d турниров", success_count, len(tournaments))
        logger.info("=" * 60)

        return results

    def _get_available_tournaments(self) -> list[str]:
        """
        Получить список доступных турниров.

        Returns:
            Список названий турниров.
        """
        tournaments = []
        for item in self.processed_root.iterdir():
            if item.is_dir():
                if (item / "train_long.parquet").exists() or (item / "train_wide.parquet").exists():
                    tournaments.append(item.name)

        return sorted(tournaments)

