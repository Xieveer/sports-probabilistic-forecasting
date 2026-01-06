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

from datetime import datetime
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.train import (
    compute_target,
    select_features,
)
from sports_forecast.training.calibration import ModelCalibrator
from sports_forecast.training.ensembles.stacking import StackingEnsemble
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel
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
        full_cfg = OmegaConf.create(
            {
                "tournament": tournament_cfg,
                "model": model_config,
            }
        )

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
            return model_class(name=model_name, config=model_config)  # type: ignore[abstract]

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
            base_model_config_path = (
                self.project_root / "conf" / "model" / f"{base_model_path}.yaml"
            )
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

    def train_tournament(
        self,
        tournament: str,
        models: list[str] | None = None,
        ensembles: list[str] | None = None,
        use_optuna: bool = False,
        use_calibration: bool = True,
    ) -> dict[str, bool]:
        """
        Обучить все модели для турнира с иерархическим MLflow логированием.

        Создаёт Parent Run для турнира и обучает все модели как Nested Runs.

        Args:
            tournament: Название турнира.
            models: Список моделей для обучения (default: ["dummy", "catboost", "lgbm", "logreg"]).
            ensembles: Список ансамблей для обучения (default: ["stacking_win"]).
            use_optuna: Использовать Optuna для оптимизации.
            use_calibration: Использовать калибровку.

        Returns:
            Словарь {model_name: success}.

        Examples:
            >>> trainer.train_tournament("uel_kz_1")
            >>> trainer.train_tournament("uel_kz_1", models=["catboost", "lgbm"])
        """
        if models is None:
            models = ["dummy", "catboost", "lgbm", "logreg"]
        if ensembles is None:
            ensembles = ["stacking_win"]

        logger.info("=" * 80)
        logger.info("ОБУЧЕНИЕ ТУРНИРА С MLFLOW PARENT RUN")
        logger.info("Tournament: %s", tournament)
        logger.info("Models: %s", ", ".join(models))
        logger.info("Ensembles: %s", ", ".join(ensembles))
        logger.info("=" * 80)

        # Определяем experiment (по типу таргета)
        # TODO: извлекать target_type из конфига модели
        experiment_name = "sports_forecast_match_winner"
        mlflow.set_experiment(experiment_name)

        # Parent Run Name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        parent_run_name = f"{tournament}_match_winner_{timestamp}"

        results = {}
        models_summary = []

        # Создаём Parent Run
        with mlflow.start_run(run_name=parent_run_name) as parent_run:
            logger.info("MLflow Parent Run: %s", parent_run.info.run_id)

            # Логируем общую информацию в Parent Run
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("target_type", "match_winner")
            mlflow.set_tag("run_type", "parent")
            mlflow.log_param("timestamp", timestamp)
            mlflow.log_param("n_models", len(models))
            mlflow.log_param("n_ensembles", len(ensembles))

            # Обучаем все single модели
            for model_name in models:
                logger.info("")
                logger.info("=" * 80)
                logger.info("Обучение модели: %s", model_name)
                logger.info("=" * 80)

                success, shadow_metrics, prod_metrics = self._train_single_internal(
                    model_name=model_name,
                    tournament=tournament,
                    use_optuna=use_optuna,
                    use_calibration=use_calibration,
                    parent_run_id=parent_run.info.run_id,
                )

                results[model_name] = success

                if success and prod_metrics:
                    models_summary.append(
                        {
                            "model": model_name,
                            "type": "single",
                            "logloss": prod_metrics.get("logloss", 0),
                            "auc": prod_metrics.get("auc", 0),
                            "accuracy": prod_metrics.get("accuracy", 0),
                            "brier": prod_metrics.get("brier", 0),
                        }
                    )

            # Обучаем все ансамбли
            for ensemble_name in ensembles:
                logger.info("")
                logger.info("=" * 80)
                logger.info("Обучение ансамбля: %s", ensemble_name)
                logger.info("=" * 80)

                success, shadow_metrics, prod_metrics = self._train_ensemble_internal(
                    ensemble_name=ensemble_name,
                    tournament=tournament,
                    parent_run_id=parent_run.info.run_id,
                )

                results[ensemble_name] = success

                if success and prod_metrics:
                    models_summary.append(
                        {
                            "model": ensemble_name,
                            "type": "ensemble",
                            "logloss": prod_metrics.get("logloss", 0),
                            "auc": prod_metrics.get("auc", 0),
                            "accuracy": prod_metrics.get("accuracy", 0),
                            "brier": prod_metrics.get("brier", 0),
                        }
                    )

            # Логируем сравнительную таблицу в Parent Run
            if models_summary:
                summary_df = pd.DataFrame(models_summary)
                summary_df = summary_df.sort_values("logloss")

                # Сохраняем как артефакт
                summary_path = self.models_root / tournament / "models_comparison.csv"
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_df.to_csv(summary_path, index=False)
                mlflow.log_artifact(str(summary_path), "comparison")

                # Логируем лучшую модель
                best_model = summary_df.iloc[0]
                mlflow.set_tag("best_model", best_model["model"])
                mlflow.log_metric("best_logloss", best_model["logloss"])
                mlflow.log_metric("best_auc", best_model["auc"])

                logger.info("")
                logger.info("=" * 80)
                logger.info("СРАВНЕНИЕ МОДЕЛЕЙ (по LogLoss):")
                logger.info("=" * 80)
                for _, row in summary_df.iterrows():
                    logger.info(
                        "  %s (%s): LogLoss=%.4f, AUC=%.4f, Acc=%.4f",
                        row["model"],
                        row["type"],
                        row["logloss"],
                        row["auc"],
                        row["accuracy"],
                    )
                logger.info("=" * 80)
                logger.info(
                    "✓ Лучшая модель: %s (LogLoss=%.4f)", best_model["model"], best_model["logloss"]
                )

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ ОБУЧЕНИЕ ТУРНИРА ЗАВЕРШЕНО")
        logger.info("=" * 80)

        return results

    def _train_single_internal(
        self,
        model_name: str,
        tournament: str,
        use_optuna: bool = False,
        use_calibration: bool = True,
        parent_run_id: str | None = None,
    ) -> tuple[bool, dict | None, dict | None]:
        """
        Внутренний метод обучения одиночной модели.

        Args:
            model_name: Название модели (catboost, lgbm, logreg, dummy).
            tournament: Название турнира.
            use_optuna: Использовать Optuna для оптимизации.
            use_calibration: Использовать калибровку.
            parent_run_id: ID parent run для nested logging (опционально).

        Returns:
            Tuple[success, shadow_metrics, prod_metrics].

        Examples:
            >>> success, shadow, prod = trainer._train_single_internal("catboost", "uel_kz_1")
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
            return False, None, None

        model_config = OmegaConf.load(model_config_path)

        # Загружаем датасет
        result = self.load_dataset_and_target(tournament, model_config)
        if result is None:
            return False, None, None

        X, y, feature_names = result

        # Train/test split (90/10 по времени)
        test_size = self.config.training.get("test_size", 0.1)
        split_idx = int(len(X) * (1 - test_size))

        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        logger.info(
            "Split: train=%d (%.1f%%), test=%d (%.1f%%)",
            len(X_train),
            (1 - test_size) * 100,
            len(X_test),
            test_size * 100,
        )

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

        # Вычисляем метрики prod модели на test set
        from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

        y_pred_proba = model.predict_proba(X_test)

        prod_metrics = {
            "logloss": log_loss(y_test, y_pred_proba),
            "auc": roc_auc_score(y_test, y_pred_proba[:, 1]) if len(set(y_test)) > 1 else 0.5,
            "accuracy": accuracy_score(y_test, y_pred_proba.argmax(axis=1)),
            "brier": brier_score_loss(y_test, y_pred_proba[:, 1]),
        }

        logger.info("Prod метрики (test set):")
        logger.info("  LogLoss:  %.4f", prod_metrics["logloss"])
        logger.info("  AUC:      %.4f", prod_metrics["auc"])
        logger.info("  Accuracy: %.4f", prod_metrics["accuracy"])
        logger.info("  Brier:    %.4f", prod_metrics["brier"])

        # Подготавливаем shadow метрики (агрегированные TSCV)
        shadow_metrics = {
            "logloss": tscv_results.get("mean_logloss", 0),
            "auc": tscv_results.get("mean_auc", 0),
            "accuracy": tscv_results.get("mean_accuracy", 0),
            "brier": tscv_results.get("mean_brier", 0),
            "ece": tscv_results.get("mean_ece", 0),
            "std_logloss": tscv_results.get("std_logloss", 0),
            "std_auc": tscv_results.get("std_auc", 0),
            "std_accuracy": tscv_results.get("std_accuracy", 0),
            "std_brier": tscv_results.get("std_brier", 0),
            "std_ece": tscv_results.get("std_ece", 0),
        }

        # MLflow логирование
        if parent_run_id:
            # Nested Run внутри Parent
            self._log_to_mlflow_single_nested(
                model_name=model_name,
                tournament=tournament,
                shadow_metrics=shadow_metrics,
                prod_metrics=prod_metrics,
                model_config=model_config,
                feature_names=feature_names,
                is_calibrated=is_calibrated,
                ece_before=ece_before,
                ece_after=ece_after,
                parent_run_id=parent_run_id,
            )
        else:
            # Старый способ (обратная совместимость)
            self._log_to_mlflow_single(
                model_name=model_name,
                tournament=tournament,
                tscv_results=tscv_results,
                model_config=model_config,
                feature_names=feature_names,
                is_calibrated=is_calibrated,
                ece_before=ece_before,
                ece_after=ece_after,
                prod_metrics=prod_metrics,
            )

        logger.info("=" * 60)
        logger.info("✓ ОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 60)

        return True, shadow_metrics, prod_metrics

    def train_single(
        self,
        model_name: str,
        tournament: str,
        use_optuna: bool = False,
        use_calibration: bool = True,
    ) -> bool:
        """
        Обучить одиночную модель для турнира (обратная совместимость).

        Использует старый способ логирования (2 отдельных run'а: shadow + prod).
        Для иерархического логирования используйте train_tournament().

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
        success, _, _ = self._train_single_internal(
            model_name=model_name,
            tournament=tournament,
            use_optuna=use_optuna,
            use_calibration=use_calibration,
            parent_run_id=None,  # Старый способ логирования
        )
        return success

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
        prod_metrics: dict | None = None,
    ) -> None:
        """
        Логировать одиночную модель в MLflow (shadow и prod отдельно).

        Args:
            model_name: Название модели.
            tournament: Название турнира.
            tscv_results: Результаты TSCV (для shadow).
            model_config: Конфигурация модели.
            feature_names: Список фичей.
            is_calibrated: Была ли применена калибровка.
            ece_before: ECE до калибровки.
            ece_after: ECE после калибровки.
            prod_metrics: Метрики prod модели на test set (опционально).
        """
        # ============================================================
        # RUN 1: SHADOW MODEL (TSCV метрики)
        # ============================================================
        run_name_shadow = f"{tournament}_{model_name}_shadow"

        with mlflow.start_run(run_name=run_name_shadow):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", model_name)
            mlflow.set_tag("model_type", "single")
            mlflow.set_tag("version", "shadow")

            # Параметры
            mlflow.log_param("n_features", len(feature_names))

            if hasattr(model_config, "params"):
                for key, value in model_config.params.items():
                    mlflow.log_param(f"model__{key}", value)

            # Shadow метрики (только агрегированные mean/std, без фолдов!)
            for metric_name, value in tscv_results.items():
                if metric_name.startswith("mean_"):
                    # Убираем префикс "mean_" для основных метрик
                    clean_name = metric_name.replace("mean_", "")
                    mlflow.log_metric(clean_name, value)
                elif metric_name.startswith("std_"):
                    # Для std оставляем как есть
                    mlflow.log_metric(metric_name, value)

            # Фичи
            mlflow.log_text("\n".join(feature_names), "features.txt")

        # ============================================================
        # RUN 2: PROD MODEL (Test set метрики)
        # ============================================================
        if prod_metrics is not None:
            run_name_prod = f"{tournament}_{model_name}_prod"

            with mlflow.start_run(run_name=run_name_prod):
                # Теги
                mlflow.set_tag("tournament", tournament)
                mlflow.set_tag("model_name", model_name)
                mlflow.set_tag("model_type", "single")
                mlflow.set_tag("version", "prod")

                # Параметры (те же, что у shadow)
                mlflow.log_param("n_features", len(feature_names))

                if hasattr(model_config, "params"):
                    for key, value in model_config.params.items():
                        mlflow.log_param(f"model__{key}", value)

                # Prod метрики
                for metric_name, value in prod_metrics.items():
                    mlflow.log_metric(metric_name, value)

                # Калибровка (только для prod)
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

    def _log_to_mlflow_single_nested(
        self,
        model_name: str,
        tournament: str,
        shadow_metrics: dict,
        prod_metrics: dict,
        model_config: DictConfig,
        feature_names: list[str],
        is_calibrated: bool,
        ece_before: float | None,
        ece_after: float | None,
        parent_run_id: str,
    ) -> None:
        """
        Логировать single модель как Nested Run внутри Parent Run.

        Args:
            model_name: Название модели.
            tournament: Название турнира.
            shadow_metrics: Shadow метрики (TSCV).
            prod_metrics: Prod метрики (test set).
            model_config: Конфигурация модели.
            feature_names: Список фичей.
            is_calibrated: Была ли применена калибровка.
            ece_before: ECE до калибровки.
            ece_after: ECE после калибровки.
            parent_run_id: ID parent run.
        """
        # Создаём Nested Run для этой модели
        with mlflow.start_run(run_name=model_name, nested=True):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", model_name)
            mlflow.set_tag("model_type", "single")
            mlflow.set_tag("parent_run_id", parent_run_id)

            # Параметры
            mlflow.log_param("n_features", len(feature_names))

            if hasattr(model_config, "params"):
                for key, value in model_config.params.items():
                    mlflow.log_param(f"model__{key}", value)

            # Shadow метрики (TSCV)
            for metric_name, value in shadow_metrics.items():
                mlflow.log_metric(f"shadow_{metric_name}", value)

            # Prod метрики (test set)
            for metric_name, value in prod_metrics.items():
                mlflow.log_metric(f"prod_{metric_name}", value)

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

            logger.info("MLflow: nested run зарегистрирован (%s)", model_name)

    def _log_to_mlflow_ensemble(
        self,
        ensemble_name: str,
        tournament: str,
        shadow_metrics: dict,
        prod_metrics: dict,
        ensemble_config: DictConfig,
        feature_names: list[str],
    ) -> None:
        """
        Логировать ансамбль в MLflow (shadow и prod отдельно).

        Args:
            ensemble_name: Название ансамбля.
            tournament: Название турнира.
            shadow_metrics: Метрики shadow модели (train set).
            prod_metrics: Метрики prod модели (test set).
            ensemble_config: Конфигурация ансамбля.
            feature_names: Список фичей.
        """
        # ============================================================
        # RUN 1: SHADOW MODEL
        # ============================================================
        run_name_shadow = f"{tournament}_{ensemble_name}_shadow"

        with mlflow.start_run(run_name=run_name_shadow):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", ensemble_name)
            mlflow.set_tag("model_type", "ensemble")
            mlflow.set_tag("ensemble_method", ensemble_config.get("ensemble_method", "stacking"))
            mlflow.set_tag("version", "shadow")

            # Параметры
            mlflow.log_param("n_features", len(feature_names))
            mlflow.log_param("n_base_models", len(ensemble_config.base_models))
            mlflow.log_param("base_models", ", ".join(ensemble_config.base_models))

            # Shadow метрики
            for metric_name, value in shadow_metrics.items():
                mlflow.log_metric(metric_name, value)

            # Фичи
            mlflow.log_text("\n".join(feature_names), "features.txt")

        # ============================================================
        # RUN 2: PROD MODEL
        # ============================================================
        run_name_prod = f"{tournament}_{ensemble_name}_prod"

        with mlflow.start_run(run_name=run_name_prod):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", ensemble_name)
            mlflow.set_tag("model_type", "ensemble")
            mlflow.set_tag("ensemble_method", ensemble_config.get("ensemble_method", "stacking"))
            mlflow.set_tag("version", "prod")

            # Параметры
            mlflow.log_param("n_features", len(feature_names))
            mlflow.log_param("n_base_models", len(ensemble_config.base_models))
            mlflow.log_param("base_models", ", ".join(ensemble_config.base_models))

            # Prod метрики
            for metric_name, value in prod_metrics.items():
                mlflow.log_metric(metric_name, value)

            # Фичи
            mlflow.log_text("\n".join(feature_names), "features.txt")

        logger.info("MLflow: ансамбль зарегистрирован (shadow + prod)")

    def _log_to_mlflow_ensemble_nested(
        self,
        ensemble_name: str,
        tournament: str,
        shadow_metrics: dict,
        prod_metrics: dict,
        ensemble_config: DictConfig,
        feature_names: list[str],
        parent_run_id: str,
    ) -> None:
        """
        Логировать ансамбль как Nested Run внутри Parent Run.

        Args:
            ensemble_name: Название ансамбля.
            tournament: Название турнира.
            shadow_metrics: Shadow метрики (train set).
            prod_metrics: Prod метрики (test set).
            ensemble_config: Конфигурация ансамбля.
            feature_names: Список фичей.
            parent_run_id: ID parent run.
        """
        # Создаём Nested Run для ансамбля
        with mlflow.start_run(run_name=ensemble_name, nested=True):
            # Теги
            mlflow.set_tag("tournament", tournament)
            mlflow.set_tag("model_name", ensemble_name)
            mlflow.set_tag("model_type", "ensemble")
            mlflow.set_tag("ensemble_method", ensemble_config.get("ensemble_method", "stacking"))
            mlflow.set_tag("parent_run_id", parent_run_id)

            # Параметры
            mlflow.log_param("n_features", len(feature_names))
            mlflow.log_param("n_base_models", len(ensemble_config.base_models))
            mlflow.log_param("base_models", ", ".join(ensemble_config.base_models))

            # Shadow метрики
            for metric_name, value in shadow_metrics.items():
                mlflow.log_metric(f"shadow_{metric_name}", value)

            # Prod метрики
            for metric_name, value in prod_metrics.items():
                mlflow.log_metric(f"prod_{metric_name}", value)

            # Фичи
            mlflow.log_text("\n".join(feature_names), "features.txt")

            logger.info("MLflow: nested run зарегистрирован (%s)", ensemble_name)

    def train_ensemble(
        self,
        ensemble_name: str,
        tournament: str,
    ) -> bool:
        """
        Обучить ансамбль для турнира (обратная совместимость).

        Использует старый способ логирования (2 отдельных run'а: shadow + prod).
        Для иерархического логирования используйте train_tournament().

        Args:
            ensemble_name: Название ансамбля (stacking_win).
            tournament: Название турнира.

        Returns:
            True если успешно, False иначе.

        Examples:
            >>> trainer.train_ensemble("stacking_win", "uel_kz_1")
        """
        success, _, _ = self._train_ensemble_internal(
            ensemble_name=ensemble_name,
            tournament=tournament,
            parent_run_id=None,  # Старый способ логирования
        )
        return success

    def _train_ensemble_internal(
        self,
        ensemble_name: str,
        tournament: str,
        parent_run_id: str | None = None,
    ) -> tuple[bool, dict | None, dict | None]:
        """
        Внутренний метод обучения ансамбля.

        Args:
            ensemble_name: Название ансамбля (stacking_win).
            tournament: Название турнира.
            parent_run_id: ID parent run для nested logging (опционально).

        Returns:
            Tuple[success, shadow_metrics, prod_metrics].

        Examples:
            >>> success, shadow, prod = trainer._train_ensemble_internal("stacking_win", "uel_kz_1")
        """
        logger.info("=" * 60)
        logger.info("ОБУЧЕНИЕ АНСАМБЛЯ")
        logger.info("Ensemble: %s", ensemble_name)
        logger.info("Tournament: %s", tournament)
        logger.info("=" * 60)

        # Загружаем конфиг ансамбля
        ensemble_config_path = (
            self.project_root / "conf" / "model" / "ensemble" / f"{ensemble_name}.yaml"
        )
        if not ensemble_config_path.exists():
            logger.error("Конфиг ансамбля не найден: %s", ensemble_config_path)
            return False, None, None

        ensemble_config = OmegaConf.load(ensemble_config_path)

        # Загружаем датасет
        result = self.load_dataset_and_target(tournament, ensemble_config)
        if result is None:
            return False, None, None

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

        # Вычисляем метрики на test set
        from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

        # Shadow метрики (взять из последнего обучения)
        # Для ансамбля мы не делаем полноценный TSCV, поэтому используем train метрики
        y_train_pred = ensemble.predict_proba(X_train)
        shadow_metrics = {
            "logloss": log_loss(y_train, y_train_pred),
            "auc": roc_auc_score(y_train, y_train_pred[:, 1]) if len(set(y_train)) > 1 else 0.5,
            "accuracy": accuracy_score(y_train, y_train_pred.argmax(axis=1)),
            "brier": brier_score_loss(y_train, y_train_pred[:, 1]),
        }

        # Prod метрики (test set)
        y_test_pred = ensemble.predict_proba(X_test)
        prod_metrics = {
            "logloss": log_loss(y_test, y_test_pred),
            "auc": roc_auc_score(y_test, y_test_pred[:, 1]) if len(set(y_test)) > 1 else 0.5,
            "accuracy": accuracy_score(y_test, y_test_pred.argmax(axis=1)),
            "brier": brier_score_loss(y_test, y_test_pred[:, 1]),
        }

        logger.info("Shadow метрики (train set):")
        logger.info("  LogLoss:  %.4f", shadow_metrics["logloss"])
        logger.info("  AUC:      %.4f", shadow_metrics["auc"])
        logger.info("  Accuracy: %.4f", shadow_metrics["accuracy"])
        logger.info("  Brier:    %.4f", shadow_metrics["brier"])

        logger.info("Prod метрики (test set):")
        logger.info("  LogLoss:  %.4f", prod_metrics["logloss"])
        logger.info("  AUC:      %.4f", prod_metrics["auc"])
        logger.info("  Accuracy: %.4f", prod_metrics["accuracy"])
        logger.info("  Brier:    %.4f", prod_metrics["brier"])

        # MLflow логирование
        if parent_run_id:
            # Nested Run внутри Parent
            self._log_to_mlflow_ensemble_nested(
                ensemble_name=ensemble_name,
                tournament=tournament,
                shadow_metrics=shadow_metrics,
                prod_metrics=prod_metrics,
                ensemble_config=ensemble_config,
                feature_names=feature_names,
                parent_run_id=parent_run_id,
            )
        else:
            # Старый способ (обратная совместимость)
            self._log_to_mlflow_ensemble(
                ensemble_name=ensemble_name,
                tournament=tournament,
                shadow_metrics=shadow_metrics,
                prod_metrics=prod_metrics,
                ensemble_config=ensemble_config,
                feature_names=feature_names,
            )

        logger.info("=" * 60)
        logger.info("✓ АНСАМБЛЬ ОБУЧЕН")
        logger.info("=" * 60)

        return True, shadow_metrics, prod_metrics

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
            if item.is_dir() and (
                (item / "train_long.parquet").exists() or (item / "train_wide.parquet").exists()
            ):
                tournaments.append(item.name)

        return sorted(tournaments)
