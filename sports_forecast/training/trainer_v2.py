"""
ExperimentRunner - оркестратор обучения для архитектуры v2.0.

Запускает nested MLflow runs согласно recipe, используя Hydra compose
для динамической композиции конфигов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import mlflow
import numpy as np
import pandas as pd
from hydra import compose, initialize_config_dir
from omegaconf import DictConfig, OmegaConf
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from sports_forecast.config import get_data_path, validate_experiment_config
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.utils.log_config import get_logger
from sports_forecast.utils.targets import (
    compute_target_from_market_spec,
    get_target_name,
)

logger = get_logger(__name__)


class ExperimentRunner:
    """
    Оркестратор запуска экспериментов согласно Recipe.

    Для каждой комбинации (algorithm, featureset, seed):
    1. Compose конфиг через Hydra
    2. Валидация эксперимента
    3. Загрузка данных и вычисление таргета
    4. Запуск nested MLflow run
    5. Обучение через ModelTrainer
    6. Логирование метрик и артефактов

    Args:
        config: Parent конфигурация (tournament, market_spec, recipe)
        project_root: Корневая директория проекта
        parent_run_id: ID parent MLflow run

    Examples:
        >>> runner = ExperimentRunner(cfg, PROJECT_ROOT, parent_run_id)
        >>> results = runner.run_all_experiments()
    """

    def __init__(
        self, config: DictConfig, project_root: Path, parent_run_id: str
    ):
        """
        Инициализация ExperimentRunner.

        Args:
            config: Parent конфигурация
            project_root: Путь к корню проекта
            parent_run_id: ID parent run для вложенности
        """
        self.config = config
        self.project_root = project_root
        self.parent_run_id = parent_run_id

        # Инициализируем Hydra для compose
        self.config_dir = str((project_root / "conf").resolve())

        logger.info("ExperimentRunner инициализирован")
        logger.info("  Project root: %s", project_root)
        logger.info("  Parent run ID: %s", parent_run_id)

    def run_all_experiments(self) -> Dict[str, bool]:
        """
        Запустить все эксперименты согласно recipe.

        Returns:
            Словарь {experiment_name: success}

        Examples:
            >>> results = runner.run_all_experiments()
            >>> # {"cb__adv__s42": True, "lgbm__basic__s42": True, ...}
        """
        recipe = self.config.recipe
        results = {}

        # Получаем списки из recipe
        algorithms = recipe.get("algorithms", [])
        featuresets = recipe.get("featuresets", [])
        seeds = recipe.get("seeds", [42])

        logger.info("Запуск %d экспериментов:", len(algorithms) * len(featuresets) * len(seeds))
        logger.info("  Algorithms: %s", algorithms)
        logger.info("  Featuresets: %s", featuresets)
        logger.info("  Seeds: %s", seeds)

        # Перебираем все комбинации
        experiment_idx = 0
        total_experiments = len(algorithms) * len(featuresets) * len(seeds)

        for algorithm_name in algorithms:
            for featureset_name in featuresets:
                for seed in seeds:
                    experiment_idx += 1

                    # Формируем имя эксперимента
                    exp_name = self._get_experiment_name(
                        algorithm_name, featureset_name, seed
                    )

                    logger.info("")
                    logger.info("─" * 80)
                    logger.info(
                        "🧪 Эксперимент %d/%d: %s",
                        experiment_idx,
                        total_experiments,
                        exp_name,
                    )
                    logger.info("─" * 80)

                    try:
                        # Запускаем эксперимент
                        success = self._run_single_experiment(
                            algorithm_name, featureset_name, seed
                        )
                        results[exp_name] = success

                        status = "✓ УСПЕХ" if success else "✗ ОШИБКА"
                        logger.info("%s: %s", status, exp_name)

                    except Exception as e:
                        logger.error(
                            "✗ ОШИБКА в эксперименте %s: %s",
                            exp_name,
                            str(e),
                            exc_info=True,
                        )
                        results[exp_name] = False

        return results

    def _run_single_experiment(
        self, algorithm_name: str, featureset_name: str, seed: int
    ) -> bool:
        """
        Запустить один эксперимент (nested run).

        Args:
            algorithm_name: Имя алгоритма (catboost, logreg, ...)
            featureset_name: Имя набора фичей (basic, advanced)
            seed: Random seed

        Returns:
            True если эксперимент успешен, иначе False
        """
        # 1. Compose конфиг для эксперимента
        cfg_experiment = self._compose_experiment_config(
            algorithm_name, featureset_name, seed
        )

        # 2. Валидация
        validate_experiment_config(cfg_experiment)

        # 3. Формируем имя и теги для nested run
        nested_run_name = self._get_experiment_name(
            algorithm_name, featureset_name, seed
        )
        nested_tags = self._get_experiment_tags(
            algorithm_name, featureset_name, seed
        )

        # 4. Запускаем nested run
        with mlflow.start_run(
            run_name=nested_run_name, nested=True, tags=nested_tags
        ) as nested_run:
            logger.info("Nested Run ID: %s", nested_run.info.run_id)

            # Логируем конфиг эксперимента
            config_str = OmegaConf.to_yaml(cfg_experiment, resolve=True)
            mlflow.log_text(config_str, "experiment_config.yaml")

            # 5. Загружаем данные
            df = self._load_data(cfg_experiment)

            # 6. Вычисляем таргет
            target = self._compute_target(df, cfg_experiment)
            target_name = get_target_name(cfg_experiment.market_spec)

            # 7. Обучаем модель через ModelTrainer (адаптируем старый trainer)
            # TODO: Пока используем упрощённую версию, потом интегрируем полный ModelTrainer
            success = self._train_model(
                df, target, target_name, cfg_experiment, nested_run.info.run_id
            )

            return success

    def _compose_experiment_config(
        self, algorithm_name: str, featureset_name: str, seed: int
    ) -> DictConfig:
        """
        Скомпоновать конфиг для эксперимента из parent config.

        Args:
            algorithm_name: Имя алгоритма
            featureset_name: Имя фичей
            seed: Random seed

        Returns:
            Полный конфиг эксперимента
        """
        # Загружаем конфиги алгоритма и фичей вручную (минуя Hydra compose)
        algorithm_path = self.project_root / "conf" / "algorithm" / f"{algorithm_name}.yaml"
        features_path = self.project_root / "conf" / "features" / f"{featureset_name}.yaml"

        if not algorithm_path.exists():
            raise FileNotFoundError(f"Algorithm config не найден: {algorithm_path}")
        if not features_path.exists():
            raise FileNotFoundError(f"Features config не найден: {features_path}")

        # Читаем конфиги
        algorithm_cfg = OmegaConf.load(algorithm_path)
        features_cfg = OmegaConf.load(features_path)

        # Клонируем parent config
        cfg_experiment = OmegaConf.create(OmegaConf.to_container(self.config, resolve=False))

        # Заменяем секции
        cfg_experiment.algorithm = algorithm_cfg
        cfg_experiment.features = features_cfg
        cfg_experiment.seed = seed

        logger.debug("Config composed: algorithm=%s, features=%s, seed=%d",
                    algorithm_name, featureset_name, seed)

        return cfg_experiment

    def _load_data(self, cfg: DictConfig) -> pd.DataFrame:
        """
        Загрузить данные на основе tournament и data_format.

        Args:
            cfg: Конфигурация эксперимента

        Returns:
            DataFrame с данными
        """
        # Получаем путь к данным
        data_format = cfg.market_spec.data_format
        data_path = get_data_path(cfg.tournament, data_format)
        full_path = self.project_root / data_path

        logger.info("Загрузка данных: %s", full_path)

        if not full_path.exists():
            raise FileNotFoundError(
                f"Файл данных не найден: {full_path}. "
                f"Запустите DVC pipeline: make dvc-repro"
            )

        df = pd.read_parquet(full_path)
        logger.info("✓ Загружено %d строк, %d колонок", len(df), len(df.columns))

        return df

    def _compute_target(self, df: pd.DataFrame, cfg: DictConfig) -> pd.Series:
        """
        Вычислить таргет на основе market_spec.

        Args:
            df: DataFrame с данными
            cfg: Конфигурация эксперимента

        Returns:
            Series с таргетом
        """
        line = cfg.market_spec.get("line") if hasattr(cfg.market_spec, "line") else None
        target = compute_target_from_market_spec(df, cfg.market_spec, line=line)
        return target

    def _train_model(
        self,
        df: pd.DataFrame,
        target: pd.Series,
        target_name: str,
        cfg: DictConfig,
        run_id: str,
    ) -> bool:
        """
        Обучить модель с TSCV и Shadow/Production сохранением.

        Полный цикл обучения:
        1. Выбор фичей
        2. Train/Test split (90/10 по времени)
        3. TSCV на train → Shadow модель
        4. Обучение на train+test → Prod модель
        5. MLflow логирование метрик

        Args:
            df: DataFrame с данными
            target: Таргет
            target_name: Имя таргета
            cfg: Конфигурация
            run_id: ID nested run

        Returns:
            True если успешно
        """
        try:
            # 1. Выбор фичей
            logger.info("🔍 Выбор фичей...")
            X, feature_names = self._select_features(df, cfg)
            y = target

            logger.info("✓ Фичи: %d колонок", len(feature_names))

            # 2. Train/Test split (90/10)
            test_size = cfg.get("split", {}).get("test_size", 0.1)
            split_idx = int(len(X) * (1 - test_size))

            X_train = X.iloc[:split_idx]
            X_test = X.iloc[split_idx:]
            y_train = y.iloc[:split_idx]
            y_test = y.iloc[split_idx:]

            logger.info(
                "✓ Split: train=%d (%.1f%%), test=%d (%.1f%%)",
                len(X_train),
                (1 - test_size) * 100,
                len(X_test),
                test_size * 100,
            )

            # 3. Создаём модель
            model = self._create_model(cfg.algorithm)

            # 4. TSCV на train → Shadow модель
            logger.info("🔄 TSCV (Shadow модель)...")
            shadow_metrics = self._train_with_tscv(
                model, X_train, y_train, cfg
            )

            # Сохраняем Shadow модель
            shadow_path = self._get_model_path(cfg, version="shadow")
            model.save(shadow_path, version="shadow")
            logger.info("✓ Shadow модель сохранена: %s", shadow_path)

            # 5. Обучение Prod модели (train + test)
            logger.info("🚀 Обучение Prod модели (train+test)...")
            X_full = pd.concat([X_train, X_test])
            y_full = pd.concat([y_train, y_test])
            model.fit(X_full, y_full)

            # Вычисляем метрики prod на test
            prod_metrics = self._evaluate_model(model, X_test, y_test)

            # Сохраняем Prod модель
            prod_path = self._get_model_path(cfg, version="prod")
            model.save(prod_path, version="prod")
            logger.info("✓ Prod модель сохранена: %s", prod_path)

            # 6. MLflow логирование
            self._log_metrics_to_mlflow(
                shadow_metrics, prod_metrics, cfg, feature_names
            )

            logger.info("✓ Обучение завершено успешно")
            return True

        except Exception as e:
            logger.error("❌ Ошибка обучения: %s", str(e), exc_info=True)
            mlflow.set_tag("error", str(e))
            return False

    def _get_experiment_name(
        self, algorithm_name: str, featureset_name: str, seed: int
    ) -> str:
        """
        Сформировать читаемое имя эксперимента.

        Args:
            algorithm_name: Имя алгоритма
            featureset_name: Имя фичей
            seed: Seed

        Returns:
            Имя в формате: alg__feat__sXXX

        Examples:
            >>> name = self._get_experiment_name("catboost", "advanced", 42)
            >>> # "cb__adv__s42"
        """
        # Сокращения для алгоритмов
        alg_short = {
            "catboost": "cb",
            "lgbm": "lgbm",
            "logreg": "lr",
            "dummy": "dum",
        }

        # Сокращения для фичей
        feat_short = {
            "basic": "bas",
            "advanced": "adv",
        }

        alg = alg_short.get(algorithm_name, algorithm_name[:4])
        feat = feat_short.get(featureset_name, featureset_name[:4])

        return f"{alg}__{feat}__s{seed}"

    def _get_experiment_tags(
        self, algorithm_name: str, featureset_name: str, seed: int
    ) -> dict:
        """
        Сформировать теги для nested run.

        Args:
            algorithm_name: Имя алгоритма
            featureset_name: Имя фичей
            seed: Seed

        Returns:
            Словарь тегов
        """
        return {
            "algorithm": algorithm_name,
            "featureset": featureset_name,
            "seed": str(seed),
            "hyper": self.config.recipe.hyper,
            "parent_run_id": self.parent_run_id,
        }

    # ─────────────────────────────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ОБУЧЕНИЯ
    # ─────────────────────────────────────────────────────────────────────────────

    def _select_features(
        self, df: pd.DataFrame, cfg: DictConfig
    ) -> tuple[pd.DataFrame, list[str]]:
        """
        Выбрать фичи для модели.

        Args:
            df: DataFrame с данными
            cfg: Конфигурация

        Returns:
            (X, feature_names)
        """
        # Исключаем служебные колонки
        exclude_cols = [
            "match_id",
            "datetime",
            "tournament",
            "status",
            "match_state",
        ]

        # Добавляем имя таргета
        target_name = get_target_name(cfg.market_spec)
        if target_name in df.columns:
            exclude_cols.append(target_name)

        # Выбираем только числовые колонки
        feature_cols = [
            col
            for col in df.columns
            if col not in exclude_cols and pd.api.types.is_numeric_dtype(df[col])
        ]

        X = df[feature_cols].copy()
        return X, feature_cols

    def _create_model(self, algorithm_cfg: DictConfig):
        """
        Создать модель по конфигурации.

        Args:
            algorithm_cfg: Конфигурация алгоритма

        Returns:
            Экземпляр модели
        """
        model_name = algorithm_cfg.name
        params = dict(algorithm_cfg.get("params", {}))

        # Определяем класс модели по _target_ или name
        target = algorithm_cfg.get("_target_", "")
        
        logger.debug("Создаём модель: %s (target=%s)", model_name, target)

        # Маппинг name → класс модели
        if "dummy" in model_name.lower() or "DummyModel" in target:
            return DummyModel(name=model_name, params=params)
        elif "logreg" in model_name.lower() or "LogRegModel" in target:
            return LogRegModel(name=model_name, params=params)
        elif "catboost" in model_name.lower() or "CatBoostModel" in target:
            return CatBoostModel(name=model_name, params=params)
        elif "lgbm" in model_name.lower() or "LGBMModel" in target:
            return LGBMModel(name=model_name, params=params)
        else:
            raise ValueError(
                f"Не удалось определить класс модели для: name={model_name}, target={target}"
            )

    def _train_with_tscv(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        cfg: DictConfig,
    ) -> dict:
        """
        Обучить модель с TSCV и вернуть агрегированные метрики.

        Args:
            model: Модель для обучения
            X_train: Обучающие фичи
            y_train: Обучающие таргеты
            cfg: Конфигурация

        Returns:
            Словарь с метриками (mean, std)
        """
        n_splits = cfg.get("split", {}).get("tscv_n_splits", 4)
        tscv = TimeSeriesCrossValidator(n_splits=n_splits)

        logger.info("  TSCV: %d фолдов", n_splits)

        tscv_results = tscv.cross_validate(model, X_train, y_train)

        # Извлекаем метрики
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

        logger.info("  TSCV метрики:")
        logger.info("    LogLoss: %.4f ± %.4f", shadow_metrics["logloss"], shadow_metrics["std_logloss"])
        logger.info("    AUC:     %.4f ± %.4f", shadow_metrics["auc"], shadow_metrics["std_auc"])
        logger.info("    ECE:     %.4f ± %.4f", shadow_metrics["ece"], shadow_metrics["std_ece"])

        return shadow_metrics

    def _evaluate_model(
        self, model: Any, X_test: pd.DataFrame, y_test: pd.Series
    ) -> dict:
        """
        Вычислить метрики модели на тестовых данных.

        Args:
            model: Обученная модель
            X_test: Тестовые фичи
            y_test: Тестовые таргеты

        Returns:
            Словарь метрик
        """
        y_pred_proba = model.predict_proba(X_test)

        metrics = {
            "logloss": log_loss(y_test, y_pred_proba),
            "auc": roc_auc_score(y_test, y_pred_proba[:, 1])
            if len(set(y_test)) > 1
            else 0.5,
            "accuracy": accuracy_score(y_test, y_pred_proba.argmax(axis=1)),
            "brier": brier_score_loss(y_test, y_pred_proba[:, 1]),
        }

        logger.info("  Prod метрики (test set):")
        logger.info("    LogLoss:  %.4f", metrics["logloss"])
        logger.info("    AUC:      %.4f", metrics["auc"])
        logger.info("    Accuracy: %.4f", metrics["accuracy"])
        logger.info("    Brier:    %.4f", metrics["brier"])

        return metrics

    def _get_model_path(self, cfg: DictConfig, version: str) -> Path:
        """
        Сформировать путь для сохранения модели.

        Args:
            cfg: Конфигурация
            version: "shadow" или "prod"

        Returns:
            Путь к модели
        """
        tournament_name = cfg.tournament.name
        algorithm_name = cfg.algorithm.name
        featureset_name = cfg.features.name
        market_spec_name = cfg.market_spec.name

        # Формат: models/{tournament}/{market_spec}/{algorithm}_{featureset}
        model_dir = (
            self.project_root
            / "models"
            / tournament_name
            / market_spec_name
            / f"{algorithm_name}_{featureset_name}"
        )
        model_dir.mkdir(parents=True, exist_ok=True)

        return model_dir

    def _log_metrics_to_mlflow(
        self,
        shadow_metrics: dict,
        prod_metrics: dict,
        cfg: DictConfig,
        feature_names: list[str],
    ) -> None:
        """
        Залогировать метрики в MLflow.

        Args:
            shadow_metrics: Метрики Shadow модели (TSCV)
            prod_metrics: Метрики Prod модели (test)
            cfg: Конфигурация
            feature_names: Список фичей
        """
        # Логируем параметры
        mlflow.log_param("algorithm", cfg.algorithm.name)
        mlflow.log_param("model_target", cfg.algorithm.get("_target_", "unknown"))
        mlflow.log_param("featureset", cfg.features.name)
        mlflow.log_param("seed", cfg.seed)
        mlflow.log_param("n_features", len(feature_names))

        # Логируем гиперпараметры модели
        if hasattr(cfg.algorithm, "params"):
            for key, value in cfg.algorithm.params.items():
                mlflow.log_param(f"model__{key}", value)

        # Shadow метрики (TSCV)
        mlflow.log_metric("shadow_logloss", shadow_metrics["logloss"])
        mlflow.log_metric("shadow_logloss_std", shadow_metrics["std_logloss"])
        mlflow.log_metric("shadow_auc", shadow_metrics["auc"])
        mlflow.log_metric("shadow_auc_std", shadow_metrics["std_auc"])
        mlflow.log_metric("shadow_accuracy", shadow_metrics["accuracy"])
        mlflow.log_metric("shadow_brier", shadow_metrics["brier"])
        mlflow.log_metric("shadow_ece", shadow_metrics["ece"])
        mlflow.log_metric("shadow_ece_std", shadow_metrics["std_ece"])

        # Prod метрики (test)
        mlflow.log_metric("prod_logloss", prod_metrics["logloss"])
        mlflow.log_metric("prod_auc", prod_metrics["auc"])
        mlflow.log_metric("prod_accuracy", prod_metrics["accuracy"])
        mlflow.log_metric("prod_brier", prod_metrics["brier"])

        # Логируем список фичей
        mlflow.log_text("\n".join(feature_names), "features.txt")

        logger.info("✓ Метрики залогированы в MLflow")

