"""
ExperimentRunner - оркестратор обучения для архитектуры v2.0.

Запускает nested MLflow runs согласно recipe, используя Hydra compose
для динамической композиции конфигов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from omegaconf import DictConfig, OmegaConf
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from sports_forecast.config import get_data_path, validate_experiment_config
from sports_forecast.training.ensembles.stacking import StackingEnsemble
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

    def __init__(self, config: DictConfig, project_root: Path, parent_run_id: str):
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

    def run_all_experiments(self) -> dict[str, bool]:
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
                    exp_name = self._get_experiment_name(algorithm_name, featureset_name, seed)

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
                        success = self._run_single_experiment(algorithm_name, featureset_name, seed)
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

    def _run_single_experiment(self, algorithm_name: str, featureset_name: str, seed: int) -> bool:
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
        cfg_experiment = self._compose_experiment_config(algorithm_name, featureset_name, seed)

        # 2. Валидация
        validate_experiment_config(cfg_experiment)

        # 3. Формируем имя и теги для nested run
        nested_run_name = self._get_experiment_name(algorithm_name, featureset_name, seed)
        nested_tags = self._get_experiment_tags(algorithm_name, featureset_name, seed)

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
            return self._train_model(
                df, target, target_name, cfg_experiment, nested_run.info.run_id
            )

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

        logger.debug(
            "Config composed: algorithm=%s, features=%s, seed=%d",
            algorithm_name,
            featureset_name,
            seed,
        )

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
                f"Файл данных не найден: {full_path}. Запустите DVC pipeline: make dvc-repro"
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
        tournament_cfg = cfg.tournament if hasattr(cfg, "tournament") else None
        return compute_target_from_market_spec(df, cfg.market_spec, tournament_cfg, line=line)

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
            # 1. Явная сортировка по времени (защита от утечек)
            time_col = cfg.get("time_column", "match_datetime")
            if time_col not in df.columns:
                # Пробуем альтернативные варианты
                if "date" in df.columns:
                    time_col = "date"
                else:
                    logger.warning(
                        "⚠️  Колонка времени '%s' не найдена! Split может быть некорректным.",
                        time_col,
                    )
                    logger.warning("  Доступные колонки: %s", list(df.columns))

            if time_col in df.columns:
                df = df.sort_values(time_col).reset_index(drop=True)
                logger.info("✓ Данные отсортированы по времени: %s", time_col)
            else:
                logger.warning("⚠️  Пропускаю сортировку (колонка не найдена)")

            # 2. Выбор фичей
            logger.info("🔍 Выбор фичей...")
            features, feature_names = self._select_features(df, cfg)
            target_series = target

            logger.info("✓ Фичи: %d колонок", len(feature_names))

            # 3. Train/Test split (90/10)
            test_size = cfg.get("split", {}).get("test_size", 0.1)
            split_idx = int(len(features) * (1 - test_size))

            train_features = features.iloc[:split_idx]
            test_features = features.iloc[split_idx:]
            train_target = target_series.iloc[:split_idx]
            test_target = target_series.iloc[split_idx:]

            logger.info(
                "✓ Split: train=%d (%.1f%%), test=%d (%.1f%%)",
                len(train_features),
                (1 - test_size) * 100,
                len(test_features),
                test_size * 100,
            )

            # 4. Создаём Shadow модель
            shadow_model = self._create_model(cfg.algorithm)

            # 5. TSCV на train → Shadow модель
            logger.info("🔄 TSCV (Shadow модель)...")
            shadow_metrics = self._train_with_tscv(shadow_model, train_features, train_target, cfg)

            # Сохраняем Shadow модель
            shadow_path = self._get_model_path(cfg, version="shadow")
            shadow_model.save(shadow_path, version="shadow")
            logger.info("✓ Shadow модель сохранена: %s", shadow_path)

            # 6. Обучение Prod модели (train + test)
            logger.info("🚀 Обучение Prod модели (train+test)...")
            prod_model = self._create_model(cfg.algorithm)
            full_features = pd.concat([train_features, test_features])
            full_target = pd.concat([train_target, test_target])
            prod_model.fit(full_features, full_target)

            # ⚠️ Метрики Prod = метрики Shadow (т.к. нет holdout для валидации Prod)
            # Prod обучена на train+test → не можем честно оценить на test
            prod_metrics = shadow_metrics.copy()
            prod_metrics["note"] = "prod_trained_on_train+test_metrics_from_shadow"
            prod_metrics["validated"] = False

            # Сохраняем Prod модель
            prod_path = self._get_model_path(cfg, version="prod")
            prod_model.save(prod_path, version="prod")
            logger.info("✓ Prod модель сохранена: %s", prod_path)

            # 7. Анализ стабильности (индикатор качества Prod)
            stability_metrics = self._analyze_training_stability(shadow_metrics)

            # 8. MLflow логирование
            self._log_metrics_to_mlflow(
                shadow_metrics, prod_metrics, stability_metrics, cfg, feature_names
            )

            logger.info("✓ Обучение завершено успешно")
            return True

        except Exception as e:
            logger.error("❌ Ошибка обучения: %s", str(e), exc_info=True)
            mlflow.set_tag("error", str(e))
            return False

    def _get_experiment_name(self, algorithm_name: str, featureset_name: str, seed: int) -> str:
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

    def _get_experiment_tags(self, algorithm_name: str, featureset_name: str, seed: int) -> dict:
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

    def _select_features(self, df: pd.DataFrame, cfg: DictConfig) -> tuple[pd.DataFrame, list[str]]:
        """
        Выбрать фичи для модели.

        Args:
            df: DataFrame с данными
            cfg: Конфигурация

        Returns:
            (features, feature_names)
        """
        # Исключаем служебные колонки
        exclude_cols = [
            "id",
            "match_id",
            "datetime",
            "tournament",
            "status",
            "match_state",
        ]

        # 🚨 КРИТИЧЕСКИ ВАЖНО: Исключаем колонки с результатами матчей (утечка таргета!)
        result_cols = [
            # Long format
            "pl_points",
            "opp_points",
            "pl",
            "opp",
            "diff_ps",
            "total_ps",
            # Wide format
            "home_points",
            "away_points",
            "home_score",
            "away_score",
            "total",
            "diff",
            # Названия команд/игроков (могут быть категориальными)
            "pl_short_name_en",
            "opp_short_name_en",
            "home_name",
            "away_name",
            "home_short_name_en",
            "away_short_name_en",
        ]
        exclude_cols.extend(result_cols)

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

        features = df[feature_cols].copy()

        # Логируем исключённые результативные колонки (для отладки)
        excluded_results = [col for col in result_cols if col in df.columns]
        if excluded_results:
            logger.debug("🔒 Исключены результативные колонки: %s", excluded_results)

        return features, feature_cols

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
        if "logreg" in model_name.lower() or "LogRegModel" in target:
            return LogRegModel(name=model_name, params=params)
        if "catboost" in model_name.lower() or "CatBoostModel" in target:
            return CatBoostModel(name=model_name, params=params)
        if "lgbm" in model_name.lower() or "LGBMModel" in target:
            return LGBMModel(name=model_name, params=params)
        if "stacking" in model_name.lower() or "StackingEnsemble" in target:
            return self._create_stacking_ensemble(algorithm_cfg)
        raise ValueError(
            f"Не удалось определить класс модели для: name={model_name}, target={target}"
        )

    def _create_stacking_ensemble(self, algorithm_cfg: DictConfig) -> StackingEnsemble:
        """
        Создать Stacking Ensemble с base_models из recipe.

        Args:
            algorithm_cfg: Конфигурация алгоритма stacking

        Returns:
            Экземпляр StackingEnsemble

        Raises:
            ValueError: Если base_models не указаны в recipe.ensemble_config
        """
        # Получаем список base_models из recipe
        if not hasattr(self.config, "recipe"):
            raise ValueError("recipe не найден в config")

        recipe = self.config.recipe
        if not hasattr(recipe, "ensemble_config") or not hasattr(
            recipe.ensemble_config, "stacking"
        ):
            raise ValueError(
                "ensemble_config.stacking не найден в recipe. "
                "Укажите base_models в recipe.ensemble_config.stacking.base_models"
            )

        base_model_names = recipe.ensemble_config.stacking.base_models
        logger.info("Создаю Stacking Ensemble с base_models: %s", base_model_names)

        # Создаём экземпляры базовых моделей напрямую (без Hydra compose)
        base_models = []

        # Маппинг имён моделей на конфигурации
        model_configs = {
            "dummy": {"name": "dummy", "params": {}},
            "logreg": {
                "name": "logreg",
                "params": {
                    "penalty": "l2",
                    "C": 1.0,
                    "solver": "saga",
                    "max_iter": 1000,
                    "random_state": 777,
                },
            },
            "catboost": {
                "name": "catboost",
                "params": {
                    "iterations": 100,
                    "depth": 6,
                    "learning_rate": 0.1,
                    "random_seed": 777,  # CatBoost использует random_seed, не random_state!
                    "verbose": 0,
                },
            },
            "lgbm": {
                "name": "lgbm",
                "params": {
                    "n_estimators": 100,
                    "max_depth": 6,
                    "learning_rate": 0.1,
                    "random_state": 777,
                    "verbose": -1,
                },
            },
        }

        for model_name in base_model_names:
            if model_name not in model_configs:
                raise ValueError(
                    f"Модель '{model_name}' не поддерживается в Stacking. "
                    f"Поддерживаются: {list(model_configs.keys())}"
                )

            cfg = model_configs[model_name]
            model_cfg_name: str = str(cfg["name"])
            model_cfg_params: dict[str, Any] = dict(cfg["params"])  # type: ignore[arg-type]

            # Создаём модель напрямую
            model: Any
            if model_name == "dummy":
                model = DummyModel(name=model_cfg_name, params=model_cfg_params)
            elif model_name == "logreg":
                model = LogRegModel(name=model_cfg_name, params=model_cfg_params)
            elif model_name == "catboost":
                model = CatBoostModel(name=model_cfg_name, params=model_cfg_params)
            elif model_name == "lgbm":
                model = LGBMModel(name=model_cfg_name, params=model_cfg_params)
            else:
                raise ValueError(f"Неизвестный тип модели: {model_name}")

            base_models.append(model)
            logger.debug("  Добавлена базовая модель: %s", model_name)

        # Создаём мета-модель
        meta_model_cfg = algorithm_cfg.meta_model
        meta_model_type = meta_model_cfg.get("type", "logreg")
        meta_model_params = dict(meta_model_cfg.get("params", {}))

        if meta_model_type == "logreg":
            meta_model = LogRegModel(name="meta_logreg", params=meta_model_params)
        else:
            raise ValueError(f"Неизвестный тип мета-модели: {meta_model_type}")

        # Создаём StackingEnsemble
        n_splits = algorithm_cfg.get("tscv_n_splits", 4)
        stacking = StackingEnsemble(
            name="stacking",
            base_models=base_models,
            meta_model=meta_model,
            config=algorithm_cfg,
            n_splits=n_splits,
        )

        logger.info(
            "✓ Stacking Ensemble создан: %d базовых моделей + %s", len(base_models), meta_model_type
        )
        return stacking

    def _train_with_tscv(
        self,
        model: Any,
        train_features: pd.DataFrame,
        train_target: pd.Series,
        cfg: DictConfig,
    ) -> dict:
        """
        Обучить модель с TSCV и вернуть агрегированные метрики.

        Args:
            model: Модель для обучения
            train_features: Обучающие фичи
            train_target: Обучающие таргеты
            cfg: Конфигурация

        Returns:
            Словарь с метриками (mean, std)
        """
        n_splits = cfg.get("split", {}).get("tscv_n_splits", 4)
        tscv = TimeSeriesCrossValidator(n_splits=n_splits)

        logger.info("  TSCV: %d фолдов", n_splits)

        tscv_results = tscv.cross_validate(model, train_features, train_target)

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
        logger.info(
            "    LogLoss: %.4f ± %.4f", shadow_metrics["logloss"], shadow_metrics["std_logloss"]
        )
        logger.info("    AUC:     %.4f ± %.4f", shadow_metrics["auc"], shadow_metrics["std_auc"])
        logger.info("    ECE:     %.4f ± %.4f", shadow_metrics["ece"], shadow_metrics["std_ece"])

        # Сохраняем детальные результаты для анализа стабильности
        shadow_metrics["fold_details"] = tscv_results

        return shadow_metrics

    def _analyze_training_stability(self, shadow_metrics: dict) -> dict:
        """
        Анализ стабильности обучения как индикатор качества Prod модели.

        Args:
            shadow_metrics: Метрики Shadow модели с TSCV

        Returns:
            Словарь с индикаторами стабильности

        Notes:
            - Низкий CV (< 10%) → модель стабильна → Prod скорее всего не деградирует
            - Высокий CV (> 20%) → модель нестабильна → Prod может быть хуже
        """
        logloss_mean = shadow_metrics.get("logloss", 0)
        logloss_std = shadow_metrics.get("std_logloss", 0)
        auc_std = shadow_metrics.get("std_auc", 0)

        # Coefficient of Variation (CV) для LogLoss
        cv_logloss = (logloss_std / logloss_mean * 100) if logloss_mean > 0 else 0

        # Оценка стабильности
        if cv_logloss < 10:
            stability_level = "high"
            prod_confidence = "high"
        elif cv_logloss < 20:
            stability_level = "medium"
            prod_confidence = "medium"
        else:
            stability_level = "low"
            prod_confidence = "low"

        stability = {
            "cv_logloss": cv_logloss,
            "std_auc": auc_std,
            "stability_level": stability_level,
            "prod_confidence": prod_confidence,
            "recommendation": (
                "Prod модель скорее всего не деградирует"
                if prod_confidence == "high"
                else "Prod модель может деградировать, нужен мониторинг"
                if prod_confidence == "medium"
                else "Prod модель нестабильна, используйте Shadow"
            ),
        }

        logger.info("📊 Анализ стабильности:")
        logger.info("  CV(LogLoss): %.2f%% → Стабильность: %s", cv_logloss, stability_level)
        logger.info("  Уверенность в Prod: %s", prod_confidence)
        logger.info("  Рекомендация: %s", stability["recommendation"])

        return stability

    def _evaluate_model(
        self, model: Any, test_features: pd.DataFrame, test_target: pd.Series
    ) -> dict:
        """
        Вычислить метрики модели на тестовых данных.

        Args:
            model: Обученная модель
            test_features: Тестовые фичи
            test_target: Тестовые таргеты

        Returns:
            Словарь метрик
        """
        pred_proba = model.predict_proba(test_features)

        metrics = {
            "logloss": log_loss(test_target, pred_proba),
            "auc": roc_auc_score(test_target, pred_proba[:, 1])
            if len(set(test_target)) > 1
            else 0.5,
            "accuracy": accuracy_score(test_target, pred_proba.argmax(axis=1)),
            "brier": brier_score_loss(test_target, pred_proba[:, 1]),
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

        return model_dir  # type: ignore[no-any-return]

    def _log_metrics_to_mlflow(
        self,
        shadow_metrics: dict,
        prod_metrics: dict,
        stability_metrics: dict,
        cfg: DictConfig,
        feature_names: list[str],
    ) -> None:
        """
        Залогировать метрики в MLflow.

        Args:
            shadow_metrics: Метрики Shadow модели (TSCV)
            prod_metrics: Метрики Prod модели (копия Shadow)
            stability_metrics: Анализ стабильности обучения
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

        # Shadow метрики (TSCV) — VALIDATED ✅
        mlflow.log_metric("shadow_logloss", shadow_metrics["logloss"])
        mlflow.log_metric("shadow_logloss_std", shadow_metrics["std_logloss"])
        mlflow.log_metric("shadow_auc", shadow_metrics["auc"])
        mlflow.log_metric("shadow_auc_std", shadow_metrics["std_auc"])
        mlflow.log_metric("shadow_accuracy", shadow_metrics["accuracy"])
        mlflow.log_metric("shadow_brier", shadow_metrics["brier"])
        mlflow.log_metric("shadow_ece", shadow_metrics["ece"])
        mlflow.log_metric("shadow_ece_std", shadow_metrics["std_ece"])
        mlflow.set_tag("shadow_validated", "true")

        # Prod метрики = Shadow метрики (т.к. нет holdout) — UNVALIDATED ⚠️
        mlflow.log_metric("prod_logloss", prod_metrics["logloss"])
        mlflow.log_metric("prod_auc", prod_metrics["auc"])
        mlflow.log_metric("prod_accuracy", prod_metrics["accuracy"])
        mlflow.log_metric("prod_brier", prod_metrics["brier"])
        mlflow.set_tag("prod_validated", "false")
        mlflow.set_tag("prod_note", prod_metrics.get("note", ""))

        # Индикаторы стабильности (для оценки качества Prod)
        mlflow.log_metric("stability_cv_logloss", stability_metrics["cv_logloss"])
        mlflow.log_metric("stability_std_auc", stability_metrics["std_auc"])
        mlflow.set_tag("stability_level", stability_metrics["stability_level"])
        mlflow.set_tag("prod_confidence", stability_metrics["prod_confidence"])
        mlflow.set_tag("recommendation", stability_metrics["recommendation"])

        # Логируем список фичей
        mlflow.log_text("\n".join(feature_names), "features.txt")

        logger.info("✓ Метрики залогированы в MLflow")
        logger.info("  Shadow: validated=true (TSCV)")
        logger.info("  Prod: validated=false (trained on train+test)")
        logger.info(
            "  Stability: %s (confidence=%s)",
            stability_metrics["stability_level"],
            stability_metrics["prod_confidence"],
        )
