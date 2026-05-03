"""
SingleExperimentRunner — оркестратор обучения одного эксперимента.

Каждый вызов — один алгоритм + один набор фичей + один seed.
Множественные эксперименты запускаются через ``hydra --multirun``.
Группировка в MLflow — через имя эксперимента.

Полный цикл обучения:
    1. Загрузка данных и вычисление таргета
    2. Выбор фичей (leakage guard + column_utils)
    3. Train/Test split по времени
    4. (Опционально) Optuna → подбор гиперпараметров
    5. TSCV → Shadow модель
    6. Калибровка (если включена и ECE > threshold)
    7. Оценка на test set (ML + Business метрики)
    8. Feature importance → MLflow
    9. Обучение Prod модели на train+test
    10. MLflow логирование всех метрик и артефактов
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
from omegaconf import DictConfig, OmegaConf
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from sports_forecast.betting.odds import extract_odds_from_raw
from sports_forecast.betting.simulator import BettingSimulator
from sports_forecast.config import get_data_path
from sports_forecast.features.column_utils import get_feature_columns
from sports_forecast.training.base import BaseModel
from sports_forecast.training.calibration import ModelCalibrator
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.training.optimization.optuna_optimizer import OptunaHyperOptimizer
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.training.train_eval_split import (
    normalize_season_token,
    subset_frame_for_season_holdout,
    uses_season_holdout_split,
)
from sports_forecast.utils.log_config import get_logger
from sports_forecast.utils.metrics import (
    compute_calibration_table,
    compute_expected_calibration_error,
    compute_max_calibration_error,
)
from sports_forecast.utils.targets import (
    compute_target_from_market_spec,
    get_target_name,
)


logger = get_logger(__name__)


class SingleExperimentRunner:
    """Оркестратор запуска одного эксперимента.

    Полный цикл:
        1. Загрузка данных и вычисление таргета
        2. Выбор фичей (с leakage guard)
        3. Train/Test split по времени
        4. (Опционально) Optuna → подбор гиперпараметров
        5. TSCV → Shadow модель
        6. Калибровка (если ECE > threshold)
        7. Оценка на test set (ML-метрики + бизнес-метрики)
        8. Feature importance → MLflow
        9. Обучение на train+test → Prod модель
        10. MLflow логирование метрик и артефактов (включая fold-level)

    Args:
        config: Hydra конфигурация (tournament, market_spec, algorithm, features).
        project_root: Корневая директория проекта.

    Examples:
        >>> runner = SingleExperimentRunner(cfg, PROJECT_ROOT)
        >>> success = runner.run_experiment()
    """

    def __init__(self, config: DictConfig, project_root: Path) -> None:
        """Инициализация SingleExperimentRunner.

        Args:
            config: Полная Hydra конфигурация.
            project_root: Путь к корню проекта.
        """
        self.config = config
        self.project_root = project_root

        logger.info("SingleExperimentRunner инициализирован")
        logger.info("  Project root: %s", project_root)
        logger.info("  Algorithm: %s", config.algorithm.name)
        logger.info("  Features: %s", config.features.name)

    def run_experiment(self) -> bool:
        """Запустить один эксперимент.

        Returns:
            True если эксперимент успешен, иначе False.
        """
        cfg = self.config

        # Формируем имя и теги для MLflow run
        run_name = self._get_run_name(cfg)
        run_tags = self._get_run_tags(cfg)

        with mlflow.start_run(run_name=run_name, tags=run_tags) as run:
            logger.info("MLflow Run ID: %s", run.info.run_id)

            # Логируем конфиг эксперимента
            config_str = OmegaConf.to_yaml(cfg, resolve=True)
            mlflow.log_text(config_str, "experiment_config.yaml")

            # Загружаем данные
            df = self._load_data(cfg)

            # Вычисляем таргет
            target = self._compute_target(df, cfg)

            # Обучаем модель
            return self._train_model(df, target, cfg, run.info.run_id)

    # ─────────────────────────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ─────────────────────────────────────────────────────────────────────────

    def _get_run_name(self, cfg: DictConfig) -> str:
        """Сформировать имя MLflow run.

        Args:
            cfg: Конфигурация.

        Returns:
            Имя в формате ``alg__feat__sXXX``.
        """
        alg_short = {
            "catboost": "cb",
            "lgbm": "lgbm",
            "logreg": "lr",
            "dummy": "dum",
        }
        feat_short = {
            "basic": "bas",
            "advanced": "adv",
        }
        alg = alg_short.get(cfg.algorithm.name, cfg.algorithm.name[:4])
        feat = feat_short.get(cfg.features.name, cfg.features.name[:4])
        seed = cfg.get("seed", 42)
        return f"{alg}__{feat}__s{seed}"

    def _get_run_tags(self, cfg: DictConfig) -> dict[str, str]:
        """Сформировать теги для MLflow run.

        Args:
            cfg: Конфигурация.

        Returns:
            Словарь тегов.
        """
        tags: dict[str, str] = {
            "tournament": cfg.tournament.name,
            "market_family": cfg.market.family,
            "market_spec": cfg.market_spec.name,
            "algorithm": cfg.algorithm.name,
            "featureset": cfg.features.name,
            "seed": str(cfg.get("seed", 42)),
            "architecture": "v2.0",
        }

        if hasattr(cfg.market_spec, "side"):
            tags["side"] = cfg.market_spec.side

        if cfg.market.family in ("total", "total_withOT", "handicap") and hasattr(
            cfg.market_spec, "line"
        ):
            tags["line"] = str(cfg.market_spec.line)

        if hasattr(cfg.market_spec, "data_format"):
            tags["data_format"] = cfg.market_spec.data_format

        return tags

    def _load_data(self, cfg: DictConfig) -> pd.DataFrame:
        """Загрузить данные на основе tournament и data_format.

        Args:
            cfg: Конфигурация эксперимента.

        Returns:
            DataFrame с данными.

        Raises:
            FileNotFoundError: Если файл данных не найден.
        """
        data_format = cfg.market_spec.data_format
        data_path = get_data_path(cfg.tournament, data_format)
        full_path = self.project_root / data_path

        logger.info("Загрузка данных: %s", full_path)

        if not full_path.exists():
            raise FileNotFoundError(
                f"Файл данных не найден: {full_path}. Запустите DVC pipeline: make dvc-repro"
            )

        df = pd.read_parquet(full_path)
        logger.info("Загружено %d строк, %d колонок", len(df), len(df.columns))
        return df

    def _compute_target(self, df: pd.DataFrame, cfg: DictConfig) -> pd.Series:
        """Вычислить таргет на основе market_spec.

        Args:
            df: DataFrame с данными.
            cfg: Конфигурация эксперимента.

        Returns:
            Series с таргетом.
        """
        line = cfg.market_spec.get("line") if hasattr(cfg.market_spec, "line") else None
        tournament_cfg = cfg.tournament if hasattr(cfg, "tournament") else None
        return compute_target_from_market_spec(df, cfg.market_spec, tournament_cfg, line=line)

    def _train_model(
        self,
        df: pd.DataFrame,
        target: pd.Series,
        cfg: DictConfig,
        run_id: str,
    ) -> bool:
        """Обучить модель с TSCV, калибровкой и бизнес-метриками.

        Args:
            df: DataFrame с данными.
            target: Таргет.
            cfg: Конфигурация.
            run_id: ID MLflow run.

        Returns:
            True если успешно.
        """
        try:
            # 1. Сортировка по времени (защита от утечек)
            time_col = cfg.get("split", {}).get("time_column", "datetime")
            if time_col not in df.columns:
                if "date" in df.columns:
                    time_col = "date"
                elif "match_datetime" in df.columns:
                    time_col = "match_datetime"
                else:
                    logger.warning(
                        "Колонка времени '%s' не найдена! Split может быть некорректным.",
                        time_col,
                    )

            if time_col in df.columns:
                df = df.sort_values(time_col).reset_index(drop=True)
                target = target.iloc[df.index].reset_index(drop=True)
                logger.info("Данные отсортированы по времени: %s", time_col)

            if uses_season_holdout_split(cfg):
                te_cfg = cfg.tournament.train_eval_split
                df, target = subset_frame_for_season_holdout(df, target, te_cfg)

            # 2. Выбор фичей
            logger.info("Выбор фичей...")
            features, feature_names = self._select_features(df, cfg)
            logger.info("Фичи: %d колонок", len(feature_names))

            # 3. Train/Test split — trailing fraction or full-season holdout
            test_size = cfg.get("split", {}).get("test_size", 0.1)
            if uses_season_holdout_split(cfg):
                te_cfg = cfg.tournament.train_eval_split
                season_col = OmegaConf.select(te_cfg, "season_column", default="season")
                holdout_tokens = {normalize_season_token(x) for x in list(te_cfg.holdout_seasons)}
                season_series = df[season_col].map(normalize_season_token)
                test_mask = season_series.isin(holdout_tokens)
                train_mask = ~test_mask
                train_features = features.loc[train_mask].reset_index(drop=True)
                test_features = features.loc[test_mask].reset_index(drop=True)
                train_target = target.loc[train_mask].reset_index(drop=True)
                test_target = target.loc[test_mask].reset_index(drop=True)
                test_df = df.loc[test_mask].reset_index(drop=True)
                logger.info(
                    "Split (season holdout): train=%d, test=%d (holdout seasons=%s)",
                    len(train_features),
                    len(test_features),
                    sorted(holdout_tokens),
                )
            else:
                split_idx = int(len(features) * (1 - test_size))
                train_features = features.iloc[:split_idx]
                test_features = features.iloc[split_idx:]
                train_target = target.iloc[:split_idx]
                test_target = target.iloc[split_idx:]
                test_df = df.iloc[split_idx:]
                logger.info(
                    "Split: train=%d (%.1f%%), test=%d (%.1f%%)",
                    len(train_features),
                    (1 - test_size) * 100,
                    len(test_features),
                    test_size * 100,
                )

            # 4. Калибровочный split (если включена калибровка)
            cal_features = None
            cal_target = None
            inner_train_features = train_features
            inner_train_target = train_target

            calibration_enabled = cfg.get("calibration", {}).get("enabled", False)
            if calibration_enabled:
                cal_size = cfg.calibration.get("validation_size", 0.1)
                cal_split_idx = int(len(train_features) * (1 - cal_size))

                inner_train_features = train_features.iloc[:cal_split_idx]
                inner_train_target = train_target.iloc[:cal_split_idx]
                cal_features = train_features.iloc[cal_split_idx:]
                cal_target = train_target.iloc[cal_split_idx:]

                logger.info(
                    "Calibration split: inner_train=%d, calibration=%d",
                    len(inner_train_features),
                    len(cal_features),
                )

            # 5. Optuna оптимизация (если включена)
            optimized_params, optuna_metrics = self._optimize_hyperparams(
                inner_train_features,
                inner_train_target,
                cfg,
            )

            # 6. Создаём Shadow модель через ModelFactory
            #    (с оптимизированными параметрами, если Optuna отработала)
            shadow_model = self._create_model(cfg.algorithm, optimized_params)

            # 7. TSCV на inner_train → Shadow модель
            logger.info("TSCV (Shadow модель)...")
            shadow_metrics = self._train_with_tscv(
                shadow_model, inner_train_features, inner_train_target, cfg
            )

            # 8. Дообучаем Shadow модель на полном inner_train
            logger.info("Дообучаем Shadow модель на полном inner_train...")
            shadow_model = self._create_model(cfg.algorithm, optimized_params)
            shadow_model.fit(inner_train_features, inner_train_target)

            # 9. Калибровка Shadow модели
            calibration_metrics: dict[str, Any] = {}
            if calibration_enabled and cal_features is not None and cal_target is not None:
                shadow_model, calibration_metrics = self._calibrate_model(
                    shadow_model,
                    cal_features,
                    cal_target,
                    test_features,
                    test_target,
                    cfg,
                )

            # 10. Оценка Shadow модели на test set
            test_ml_metrics = self._evaluate_on_test(
                shadow_model,
                test_features,
                test_target,
            )

            # 11. Бизнес-метрики на test set
            business_metrics = self._compute_business_metrics(
                shadow_model,
                test_features,
                test_target,
                test_df,
                cfg,
            )

            # 12. Feature importance
            feature_importance = self._get_feature_importance(shadow_model)

            # 12.1. Feature Selection (если включён)
            feature_selection_result = self._run_feature_selection(
                shadow_model,
                train_features,
                train_target,
                cfg,
            )

            # Снимок метрик модели на полном наборе фичей (до переобучения на подмножестве)
            test_metrics_full = dict(test_ml_metrics)
            business_metrics_full = dict(business_metrics) if business_metrics else {}
            shadow_metrics_full = dict(shadow_metrics)
            calibration_metrics_full = dict(calibration_metrics) if calibration_metrics else {}
            feature_importance_full = (
                feature_importance.copy()
                if feature_importance is not None and not feature_importance.empty
                else feature_importance
            )

            metrics_fs_fit: dict[str, Any] | None = None
            fs_cfg = cfg.get("feature_selection", {})
            if (
                feature_selection_result is not None
                and feature_selection_result.n_selected > 0
                and fs_cfg.get("apply_selected_to_fit", False)
            ):
                selected_cols = [
                    c
                    for c in feature_selection_result.selected_features
                    if c in train_features.columns
                ]
                if not selected_cols:
                    logger.warning(
                        "apply_selected_to_fit=true, но ни одна отобранная колонка "
                        "не найдена в train_features — пропуск переобучения"
                    )
                else:
                    dropped = len(feature_selection_result.selected_features) - len(selected_cols)
                    if dropped:
                        logger.warning(
                            "apply_selected_to_fit: %d имён из отбора отсутствуют в данных",
                            dropped,
                        )
                    logger.info(
                        f"{'=' * 60}\n"
                        f"ПЕРЕОБУЧЕНИЕ НА ОТОБРАННЫХ ФИЧАХ ({len(selected_cols)} колонок)\n"
                        f"{'=' * 60}",
                    )
                    inner_train_features = inner_train_features[selected_cols]
                    if cal_features is not None:
                        cal_features = cal_features[selected_cols]
                    test_features = test_features[selected_cols]
                    train_features = train_features[selected_cols]
                    feature_names = selected_cols

                    shadow_model = self._create_model(cfg.algorithm, optimized_params)
                    logger.info("TSCV (Shadow после отбора фичей)...")
                    shadow_metrics = self._train_with_tscv(
                        shadow_model,
                        inner_train_features,
                        inner_train_target,
                        cfg,
                    )
                    logger.info("Дообучаем Shadow на inner_train (отобранные фичи)...")
                    shadow_model = self._create_model(cfg.algorithm, optimized_params)
                    shadow_model.fit(inner_train_features, inner_train_target)

                    calibration_metrics = {}
                    if calibration_enabled and cal_features is not None and cal_target is not None:
                        shadow_model, calibration_metrics = self._calibrate_model(
                            shadow_model,
                            cal_features,
                            cal_target,
                            test_features,
                            test_target,
                            cfg,
                        )

                    test_ml_metrics = self._evaluate_on_test(
                        shadow_model,
                        test_features,
                        test_target,
                    )
                    business_metrics = self._compute_business_metrics(
                        shadow_model,
                        test_features,
                        test_target,
                        test_df,
                        cfg,
                    )
                    feature_importance = self._get_feature_importance(shadow_model)

                    metrics_fs_fit = {
                        "test": dict(test_ml_metrics),
                        "business": dict(business_metrics) if business_metrics else {},
                        "shadow": dict(shadow_metrics),
                        "calibration": dict(calibration_metrics) if calibration_metrics else {},
                        "feature_importance": feature_importance,
                    }
                    # Возвращаем «полный набор» метрик для основных MLflow-ключей
                    test_ml_metrics = test_metrics_full
                    business_metrics = business_metrics_full
                    shadow_metrics = shadow_metrics_full
                    calibration_metrics = calibration_metrics_full

                    logger.info(
                        "Сравнение holdout logloss: полный набор=%.4f, "
                        "после отбора и переобучения=%.4f",
                        test_metrics_full.get("logloss", float("nan")),
                        metrics_fs_fit["test"].get("logloss", float("nan")),
                    )

            # 13. Сохраняем Shadow модель
            shadow_path = self._get_model_path(cfg, version="shadow")
            shadow_model.save(shadow_path, version="shadow")
            self._save_feature_names(shadow_path, feature_names)
            logger.info("Shadow модель сохранена: %s", shadow_path)

            # 14. Обучение Prod модели (train + test)
            logger.info("Обучение Prod модели (train+test)...")
            prod_model = self._create_model(cfg.algorithm, optimized_params)
            full_features = pd.concat([train_features, test_features])
            full_target = pd.concat([train_target, test_target])
            prod_model.fit(full_features, full_target)

            # 15. Сохраняем Prod модель
            prod_path = self._get_model_path(cfg, version="prod")
            prod_model.save(prod_path, version="prod")
            self._save_feature_names(prod_path, feature_names)
            logger.info("Prod модель сохранена: %s", prod_path)

            # 15.1. MLflow: логируем артефакты модели и регистрируем в Model Registry
            self._register_model_in_mlflow(prod_path, cfg)

            # 16. Анализ стабильности (по shadow после отбора, если был переобучен prod на subset)
            stability_shadow = metrics_fs_fit["shadow"] if metrics_fs_fit else shadow_metrics
            stability_metrics = self._analyze_training_stability(stability_shadow)

            # 17. MLflow логирование
            self._log_metrics_to_mlflow(
                shadow_metrics=shadow_metrics,
                test_metrics=test_ml_metrics,
                calibration_metrics=calibration_metrics,
                business_metrics=business_metrics,
                stability_metrics=stability_metrics,
                optuna_metrics=optuna_metrics,
                feature_importance=feature_importance_full
                if metrics_fs_fit
                else feature_importance,
                feature_selection_result=feature_selection_result,
                cfg=cfg,
                feature_names=feature_names,
                metrics_fs_fit=metrics_fs_fit,
            )

            logger.info("Обучение завершено успешно")
            return True

        except Exception as e:
            logger.error("Ошибка обучения: %s", str(e), exc_info=True)
            mlflow.set_tag("error", str(e))
            return False

    def _select_features(self, df: pd.DataFrame, cfg: DictConfig) -> tuple[pd.DataFrame, list[str]]:
        """Выбрать фичи для модели (с leakage guard).

        Стратегия выбора:
            1. Если в ``market_spec.feature_prefixes`` заданы префиксы
               (например ``["home_f_", "away_f_"]`` для wide format) —
               используем их.
            2. Если есть колонки с префиксом ``f_`` (из FeaturePipeline) —
               используем ``column_utils.get_feature_columns()``.
            3. Иначе — fallback: все числовые колонки минус exclude/result.

        Args:
            df: DataFrame с данными.
            cfg: Конфигурация.

        Returns:
            Кортеж (features DataFrame, список имён фичей).
        """
        # Стратегия 1: Явные префиксы из market_spec (wide format)
        feature_prefixes = list(cfg.market_spec.get("feature_prefixes", []))
        if feature_prefixes:
            f_cols = get_feature_columns(df, prefixes=feature_prefixes)
            if f_cols:
                logger.info(
                    "Используем %d колонок с префиксами %s (wide format)",
                    len(f_cols),
                    feature_prefixes,
                )
                features = df[f_cols].copy()
                return features, f_cols

        # Стратегия 2: Колонки с префиксом f_ (long format, предпочтительная)
        f_cols = get_feature_columns(df)
        if f_cols:
            logger.info(
                "Используем %d колонок с префиксом f_ (FeaturePipeline)",
                len(f_cols),
            )
            features = df[f_cols].copy()
            return features, f_cols

        # Стратегия 2: Fallback — все числовые минус exclude/result
        logger.warning(
            "Колонки с префиксом f_ не найдены. "
            "Используем fallback: все числовые минус exclude_cols + result_cols"
        )
        exclude_cols = list(cfg.features.get("exclude_cols", []))
        result_cols = list(cfg.features.get("result_cols", []))
        exclude_cols.extend(result_cols)

        # Добавляем имя таргета
        target_name = get_target_name(cfg.market_spec)
        if target_name in df.columns:
            exclude_cols.append(target_name)

        # Выбираем только числовые колонки, не входящие в exclude
        feature_cols = [
            col
            for col in df.columns
            if col not in exclude_cols and pd.api.types.is_numeric_dtype(df[col])
        ]

        features = df[feature_cols].copy()

        # Логируем исключённые результативные колонки
        excluded_results = [col for col in result_cols if col in df.columns]
        if excluded_results:
            logger.debug("Исключены результативные колонки: %s", excluded_results)

        return features, feature_cols

    def _create_model(
        self,
        algorithm_cfg: DictConfig,
        optimized_params: dict[str, Any] | None = None,
    ) -> BaseModel:
        """Создать модель по конфигурации, используя ModelFactory.

        Если ``optimized_params`` переданы (после Optuna), они мержатся
        с дефолтными параметрами алгоритма.

        Args:
            algorithm_cfg: Конфигурация алгоритма.
            optimized_params: Оптимизированные гиперпараметры (опционально).

        Returns:
            Экземпляр модели (BaseModel).
        """
        if optimized_params:
            logger.debug(
                "Создаём модель '%s' с оптимизированными параметрами",
                algorithm_cfg.name,
            )
            cfg_dict = OmegaConf.to_container(algorithm_cfg, resolve=True)
            cfg_dict["params"] = optimized_params
            merged_cfg = OmegaConf.create(cfg_dict)
            return ModelFactory.create_model(merged_cfg)

        logger.debug("Создаём модель: %s", algorithm_cfg.name)
        return ModelFactory.create_model(algorithm_cfg)

    def _optimize_hyperparams(
        self,
        train_features: pd.DataFrame,
        train_target: pd.Series,
        cfg: DictConfig,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Запустить Optuna оптимизацию гиперпараметров (если включена).

        Args:
            train_features: Обучающие фичи.
            train_target: Обучающий таргет.
            cfg: Конфигурация.

        Returns:
            Кортеж (оптимизированные параметры или None, метрики Optuna).
        """
        hyper_cfg = cfg.get("hyper", {})
        if not hyper_cfg.get("enabled", False):
            logger.info("Optuna оптимизация отключена (hyper.enabled=false)")
            return None, {}

        # Проверяем наличие optuna_space
        optuna_space = cfg.algorithm.get("optuna_space", None)
        if optuna_space is None:
            logger.warning(
                "optuna_space не задан для '%s', пропускаем оптимизацию",
                cfg.algorithm.name,
            )
            return None, {}

        # Формируем имя study
        tournament = cfg.tournament.name
        market_spec = cfg.market_spec.name
        algorithm = cfg.algorithm.name
        study_name = f"{tournament}__{market_spec}__{algorithm}"

        split_cfg = cfg.get("split", None)

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=cfg.algorithm,
            hyper_cfg=hyper_cfg,
            split_cfg=split_cfg,
            study_name=study_name,
        )

        best_params = optimizer.optimize(train_features, train_target)

        # Логируем в MLflow
        optimizer.log_to_mlflow(best_params)

        optuna_metrics: dict[str, Any] = {
            "enabled": True,
            "best_params": best_params,
            "study_name": study_name,
        }

        logger.info("Optuna: лучшие параметры найдены для '%s'", algorithm)
        return best_params, optuna_metrics

    def _get_feature_importance(
        self,
        model: BaseModel,
    ) -> pd.DataFrame | None:
        """Получить важность фичей от обученной модели.

        Args:
            model: Обученная модель.

        Returns:
            DataFrame с feature importance или None.
        """
        importance = model.get_feature_importance()
        if importance is not None and not importance.empty:
            logger.info(
                "Feature importance: top-5 фичей:\n%s",
                importance.head(5).to_string(index=False),
            )
        else:
            logger.debug(
                "Feature importance недоступна для '%s'",
                model.get_name(),
            )
        return importance

    def _run_feature_selection(
        self,
        model: BaseModel,
        train_features: pd.DataFrame,
        train_target: pd.Series,
        cfg: DictConfig,
    ) -> Any:
        """Запустить Feature Selection (если включён в конфиге).

        Args:
            model: Обученная Shadow модель.
            train_features: Обучающие фичи.
            train_target: Обучающий таргет.
            cfg: Конфигурация.

        Returns:
            FeatureSelectionResult или None если отключён.
        """
        from sports_forecast.features.selection.selector import FeatureSelector

        fs_cfg = cfg.get("feature_selection", {})
        if not fs_cfg.get("enabled", False):
            logger.info("Feature Selection отключён (feature_selection.enabled=false)")
            return None

        logger.info("=" * 60)
        logger.info("FEATURE SELECTION")
        logger.info("=" * 60)

        selector = FeatureSelector.from_config(fs_cfg)
        result = selector.select(train_features, train_target, model=model)

        # Сохраняем в файл если настроено
        if fs_cfg.get("save_selected_features", True):
            model_path = self._get_model_path(cfg, version="shadow")
            selected_path = model_path.parent / "selected_features.txt"
            result.save_selected(selected_path)

            ranking_path = model_path.parent / "feature_ranking.csv"
            result.save_ranking(ranking_path)

        return result

    def _train_with_tscv(
        self,
        model: Any,
        train_features: pd.DataFrame,
        train_target: pd.Series,
        cfg: DictConfig,
    ) -> dict[str, Any]:
        """Обучить модель с TSCV и вернуть агрегированные метрики.

        Args:
            model: Модель для обучения.
            train_features: Обучающие фичи.
            train_target: Обучающие таргеты.
            cfg: Конфигурация.

        Returns:
            Словарь с метриками (mean, std).
        """
        n_splits = cfg.get("split", {}).get("tscv_n_splits", 4)
        tscv = TimeSeriesCrossValidator(n_splits=n_splits)

        logger.info("  TSCV: %d фолдов", n_splits)

        tscv_results = tscv.cross_validate(model, train_features, train_target)

        shadow_metrics: dict[str, Any] = {
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
            "    LogLoss: %.4f +/- %.4f",
            shadow_metrics["logloss"],
            shadow_metrics["std_logloss"],
        )
        logger.info(
            "    AUC:     %.4f +/- %.4f",
            shadow_metrics["auc"],
            shadow_metrics["std_auc"],
        )
        logger.info(
            "    ECE:     %.4f +/- %.4f",
            shadow_metrics["ece"],
            shadow_metrics["std_ece"],
        )

        shadow_metrics["fold_details"] = tscv_results
        return shadow_metrics

    def _calibrate_model(
        self,
        model: BaseModel,
        cal_features: pd.DataFrame,
        cal_target: pd.Series,
        val_features: pd.DataFrame,
        val_target: pd.Series,
        cfg: DictConfig,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Калибровать модель если ECE превышает порог.

        Args:
            model: Обученная модель.
            cal_features: Фичи для калибровки.
            cal_target: Таргет для калибровки.
            val_features: Фичи для оценки калибровки.
            val_target: Таргет для оценки калибровки.
            cfg: Конфигурация.

        Returns:
            Кортеж (модель, метрики калибровки).
        """
        logger.info("=" * 60)
        logger.info("КАЛИБРОВКА МОДЕЛИ")
        logger.info("=" * 60)

        cal_cfg = cfg.calibration
        threshold_ece = cal_cfg.get("threshold_ece", 0.10)
        method = cal_cfg.get("method", "isotonic")
        cv = cal_cfg.get("cv", "prefit")

        calibrator = ModelCalibrator(
            threshold_ece=threshold_ece,
            method=method,
            cv=cv,
        )

        calibrated_model, is_calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
            model=model,
            cal_features=cal_features,
            cal_target=cal_target,
            val_features=val_features,
            val_target=val_target,
        )

        metrics: dict[str, Any] = {
            "is_calibrated": is_calibrated,
            "ece_before": ece_before,
            "ece_after": ece_after,
            "method": method,
            "threshold": threshold_ece,
        }

        if is_calibrated:
            logger.info(
                "✓ Калибровка применена: ECE %.4f → %.4f (метод: %s)",
                ece_before,
                ece_after,
                method,
            )
        elif ece_before <= threshold_ece:
            logger.info(
                "\u2713 Калибровка не требуется: ECE %.4f ≤ порога %.4f",
                ece_before,
                threshold_ece,
            )
        else:
            logger.info(
                "\u2713 Калибровка не применена: на val ECE не улучшился "
                "(до %.4f, после %.4f; порог для попытки %.4f)",
                ece_before,
                ece_after,
                threshold_ece,
            )

        return calibrated_model, metrics

    def _evaluate_on_test(
        self,
        model: BaseModel,
        test_features: pd.DataFrame,
        test_target: pd.Series,
    ) -> dict[str, float]:
        """Вычислить ML-метрики на test set.

        Args:
            model: Обученная (возможно калиброванная) модель.
            test_features: Тестовые фичи.
            test_target: Тестовый таргет.

        Returns:
            Словарь ML-метрик.
        """
        logger.info("=" * 60)
        logger.info("ОЦЕНКА НА TEST SET")
        logger.info("=" * 60)

        proba = model.predict_proba(test_features)[:, 1]
        y_pred = (proba >= 0.5).astype(int)

        metrics: dict[str, float] = {}

        try:
            metrics["logloss"] = float(log_loss(test_target, proba))
        except Exception as e:
            logger.warning("LogLoss ошибка: %s", e)
            metrics["logloss"] = 0.0

        try:
            metrics["auc"] = float(roc_auc_score(test_target, proba))
        except Exception as e:
            logger.warning("AUC ошибка: %s", e)
            metrics["auc"] = 0.0

        try:
            metrics["accuracy"] = float(accuracy_score(test_target, y_pred))
        except Exception as e:
            logger.warning("Accuracy ошибка: %s", e)
            metrics["accuracy"] = 0.0

        try:
            metrics["brier"] = float(brier_score_loss(test_target, proba))
        except Exception as e:
            logger.warning("Brier ошибка: %s", e)
            metrics["brier"] = 0.0

        try:
            metrics["ece"] = float(compute_expected_calibration_error(np.array(test_target), proba))
        except Exception as e:
            logger.warning("ECE ошибка: %s", e)
            metrics["ece"] = 0.0

        try:
            metrics["mce"] = float(compute_max_calibration_error(np.array(test_target), proba))
        except Exception as e:
            logger.warning("MCE ошибка: %s", e)
            metrics["mce"] = 0.0

        logger.info("  Test LogLoss:  %.4f", metrics["logloss"])
        logger.info("  Test AUC:      %.4f", metrics["auc"])
        logger.info("  Test Accuracy: %.4f", metrics["accuracy"])
        logger.info("  Test Brier:    %.4f", metrics["brier"])
        logger.info("  Test ECE:      %.4f", metrics["ece"])
        logger.info("  Test MCE:      %.4f", metrics["mce"])

        return metrics

    def _compute_business_metrics(
        self,
        model: BaseModel,
        test_features: pd.DataFrame,
        test_target: pd.Series,
        test_df: pd.DataFrame,
        cfg: DictConfig,
    ) -> dict[str, Any]:
        """Вычислить бизнес-метрики через BettingSimulator.

        Полный набор:
            - Volume: n_bets, turnover, coverage
            - Profit: profit_units, ROI, avg_profit_per_bet
            - Edge/EV: avg_edge, avg_ev, ev_sum, ev_realization
            - Risk: max_drawdown, sharpe, profit_factor
            - Calibration on selected: brier, logloss, ECE
            - Odds-bin breakdown
            - Threshold sweep (артефакт)

        Args:
            model: Обученная модель.
            test_features: Тестовые фичи.
            test_target: Тестовый таргет.
            test_df: Полный DataFrame test set (для odds).
            cfg: Конфигурация.

        Returns:
            Словарь бизнес-метрик (пустой если odds не найдены).
        """
        betting_cfg = cfg.get("betting", {})
        if not betting_cfg.get("enabled", False):
            logger.info("BettingSimulator отключён (betting.enabled=false)")
            return {}

        # Извлекаем odds из raw-колонки (dict string → numeric)
        bookmaker_cfg = cfg.get("bookmaker", {})
        odds = extract_odds_from_raw(test_df, cfg.market_spec, bookmaker_cfg)
        valid_odds_mask = odds.notna() & (odds > 1.0)
        valid_count = int(valid_odds_mask.sum())

        if valid_count == 0:
            logger.warning(
                "Не удалось извлечь валидные odds из odds_raw "
                "(market=%s) → бизнес-метрики пропущены",
                cfg.market_spec.name,
            )
            return {}

        logger.info("=" * 60)
        logger.info("БИЗНЕС-МЕТРИКИ (BettingSimulator)")
        logger.info("  Market: %s", cfg.market_spec.name)
        logger.info("  Валидных odds: %d / %d", valid_count, len(odds))
        logger.info("=" * 60)

        # Фильтруем данные с валидными odds
        valid_features = test_features.loc[valid_odds_mask]
        valid_target = test_target.loc[valid_odds_mask]
        valid_odds = odds.loc[valid_odds_mask]
        proba = model.predict_proba(valid_features)[:, 1]

        y_true_arr = np.array(valid_target)
        odds_arr = np.array(valid_odds)

        # ── 1. Main simulation ───────────────────────────────────────────
        simulator = BettingSimulator(
            initial_bankroll=betting_cfg.get("initial_bankroll", 1000.0),
            stake_strategy=betting_cfg.get("stake_strategy", "flat"),
            flat_stake=betting_cfg.get("flat_stake", 10.0),
            kelly_fraction=betting_cfg.get("kelly_fraction", 0.25),
            min_value_threshold=betting_cfg.get("min_value_threshold", 0.05),
            max_stake_fraction=betting_cfg.get("max_stake_fraction", 0.1),
        )

        result = simulator.simulate(
            y_true=y_true_arr,
            y_pred_proba=proba,
            odds=odds_arr,
        )

        # ── 2. Calibration on selected bets ──────────────────────────────
        cal_selected = self._compute_calibration_on_selected(y_true_arr, proba, result.bet_mask)

        # ── 3. Odds-bin analysis ─────────────────────────────────────────
        odds_bins_cfg = betting_cfg.get("odds_bins", {})
        bins = list(odds_bins_cfg.get("bins", [1.0, 2.0, 3.0, 5.0, 999.0]))
        bin_labels = list(odds_bins_cfg.get("labels", ["1_2", "2_3", "3_5", "5_plus"]))
        odds_bin_metrics = BettingSimulator.compute_odds_bin_metrics(
            y_true_arr,
            proba,
            odds_arr,
            result.bet_mask,
            bins=bins,
            labels=bin_labels,
        )

        # ── 4. Threshold sweep ───────────────────────────────────────────
        sweep_cfg = betting_cfg.get("threshold_sweep", {})
        sweep_df: pd.DataFrame | None = None
        if sweep_cfg.get("enabled", True):
            thr_min = sweep_cfg.get("min", 0.0)
            thr_max = sweep_cfg.get("max", 0.30)
            thr_step = sweep_cfg.get("step", 0.01)
            thresholds = np.round(np.arange(thr_min, thr_max + thr_step / 2, thr_step), 4).tolist()
            sweep_df = simulator.sweep_thresholds(y_true_arr, proba, odds_arr, thresholds)

        # ── 5. Calibration table (reliability diagram data) ──────────────
        cal_table = compute_calibration_table(y_true_arr, proba)

        # ── Compose result dict ──────────────────────────────────────────
        metrics: dict[str, Any] = {
            # Volume
            "n_total_events": result.n_total_events,
            "n_bets": result.n_bets,
            "turnover_units": result.turnover_units,
            "coverage": result.coverage,
            # Profit
            "profit_units": result.profit_units,
            "roi": result.roi,
            "avg_profit_per_bet": result.avg_profit_per_bet,
            # Edge / EV
            "avg_edge": result.avg_edge,
            "avg_ev": result.avg_ev,
            "ev_sum_units": result.ev_sum_units,
            "ev_realization": result.ev_realization,
            # Win / Loss
            "hit_rate": result.hit_rate,
            "num_wins": result.num_wins,
            # Risk
            "max_drawdown_units": result.max_drawdown_units,
            "max_drawdown_pct": result.max_drawdown_pct,
            "std_return_per_bet": result.std_return_per_bet,
            "sharpe_like": result.sharpe_like,
            "profit_factor": result.profit_factor,
            # Averages
            "avg_odds": result.avg_odds,
            "final_bankroll": result.final_bankroll,
            # Calibration on selected
            **{f"cal_selected_{k}": v for k, v in cal_selected.items()},
            # Odds bins
            "odds_bin_metrics": odds_bin_metrics,
            # Artifacts data
            "equity_curve": result.equity_curve,
            "sweep_df": sweep_df,
            "cal_table": cal_table,
            # Meta
            "odds_column": f"odds_raw→{cfg.market_spec.name}",
            "valid_odds_count": valid_count,
        }

        return metrics

    def _compute_calibration_on_selected(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        bet_mask: np.ndarray,
    ) -> dict[str, float]:
        """Вычислить метрики калибровки на отобранных ставках.

        Args:
            y_true: Реальные исходы.
            y_pred_proba: Предсказанные вероятности.
            bet_mask: Маска отобранных ставок.

        Returns:
            Словарь ``{brier, logloss, ece}``.
        """
        from sklearn.metrics import brier_score_loss, log_loss

        selected_y = y_true[bet_mask]
        selected_p = y_pred_proba[bet_mask]

        if len(selected_y) < 2:
            return {"brier": 0.0, "logloss": 0.0, "ece": 0.0}

        result: dict[str, float] = {}
        try:
            result["brier"] = float(brier_score_loss(selected_y, selected_p))
        except Exception:
            result["brier"] = 0.0
        try:
            result["logloss"] = float(log_loss(selected_y, selected_p))
        except Exception:
            result["logloss"] = 0.0
        try:
            result["ece"] = float(compute_expected_calibration_error(selected_y, selected_p))
        except Exception:
            result["ece"] = 0.0

        logger.info(
            "  Calibration on selected (%d bets): brier=%.4f, logloss=%.4f, ece=%.4f",
            len(selected_y),
            result["brier"],
            result["logloss"],
            result["ece"],
        )
        return result

    def _save_feature_names(self, model_dir: Path, feature_names: list[str]) -> None:
        """Сохранить список фичей в директорию модели.

        Сохраняет ``features.txt`` рядом с файлом модели,
        чтобы ``predict.py`` мог загрузить тот же набор фичей.

        Args:
            model_dir: Директория модели.
            feature_names: Список имён фичей.
        """
        features_path = model_dir / "features.txt"
        features_path.write_text("\n".join(feature_names))
        logger.debug("features.txt сохранён: %s (%d фичей)", features_path, len(feature_names))

    def _analyze_training_stability(self, shadow_metrics: dict[str, Any]) -> dict[str, Any]:
        """Анализ стабильности обучения как индикатор качества Prod модели.

        Args:
            shadow_metrics: Метрики Shadow модели с TSCV.

        Returns:
            Словарь с индикаторами стабильности.

        Notes:
            - Низкий CV (< 10%) → модель стабильна.
            - Высокий CV (> 20%) → модель нестабильна.
        """
        logloss_mean = shadow_metrics.get("logloss", 0)
        logloss_std = shadow_metrics.get("std_logloss", 0)
        auc_std = shadow_metrics.get("std_auc", 0)

        cv_logloss = (logloss_std / logloss_mean * 100) if logloss_mean > 0 else 0

        if cv_logloss < 10:
            stability_level = "high"
            prod_confidence = "high"
        elif cv_logloss < 20:
            stability_level = "medium"
            prod_confidence = "medium"
        else:
            stability_level = "low"
            prod_confidence = "low"

        stability: dict[str, Any] = {
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

        logger.info("Анализ стабильности:")
        logger.info(
            "  CV(LogLoss): %.2f%% → Стабильность: %s",
            cv_logloss,
            stability_level,
        )
        logger.info("  Уверенность в Prod: %s", prod_confidence)
        logger.info("  Рекомендация: %s", stability["recommendation"])

        return stability

    def _get_model_path(self, cfg: DictConfig, version: str) -> Path:
        """Сформировать путь для сохранения модели.

        Args:
            cfg: Конфигурация.
            version: ``"shadow"`` или ``"prod"``.

        Returns:
            Путь к директории модели.
        """
        tournament_name = str(cfg.tournament.name)
        algorithm_name = str(cfg.algorithm.name)
        featureset_name = str(cfg.features.name)
        market_spec_name = str(cfg.market_spec.name)

        model_dir = (
            self.project_root
            / "models"
            / tournament_name
            / market_spec_name
            / f"{algorithm_name}_{featureset_name}"
        )
        model_dir.mkdir(parents=True, exist_ok=True)
        return model_dir

    def _register_model_in_mlflow(self, model_path: Path, cfg: DictConfig) -> None:
        """Логировать артефакты модели и зарегистрировать в MLflow Model Registry.

        Используем ``mlflow.pyfunc.log_model`` для создания полноценной
        logged model, чтобы ``mlflow.register_model`` мог её найти.

        Args:
            model_path: Директория с файлами модели.
            cfg: Hydra конфигурация.
        """
        try:
            # Логируем всю директорию модели как артефакт
            mlflow.log_artifacts(str(model_path), artifact_path="model_artifacts")
            logger.info("Артефакты модели залогированы в MLflow: %s", model_path)

            # Регистрируем модель в Model Registry через pyfunc
            tournament = cfg.tournament.name
            market_spec = cfg.market_spec.name
            algorithm = cfg.algorithm.name
            featureset = cfg.features.name

            model_name = f"{tournament}__{market_spec}__{algorithm}_{featureset}"

            # Определяем и логируем модель через flavor-specific API
            model_info = self._log_model_with_flavor(algorithm, model_path)

            if model_info is not None:
                result = mlflow.register_model(model_info.model_uri, model_name)
                logger.info(
                    "Модель зарегистрирована в MLflow Registry: %s v%s",
                    model_name,
                    result.version,
                )

                # Добавляем описание
                from mlflow.tracking import MlflowClient

                client = MlflowClient()
                client.update_model_version(
                    name=model_name,
                    version=result.version,
                    description=(
                        f"Tournament: {tournament}, Market: {market_spec}, "
                        f"Algorithm: {algorithm}, Features: {featureset}"
                    ),
                )
            else:
                logger.info(
                    "Flavor-specific log_model недоступен для '%s', "
                    "артефакты залогированы без Registry",
                    algorithm,
                )

        except Exception:
            logger.warning(
                "Не удалось зарегистрировать модель в MLflow Registry (не критично)",
                exc_info=True,
            )

    def _log_model_with_flavor(
        self,
        algorithm: str,
        model_path: Path,
    ) -> Any:
        """Залогировать модель через MLflow flavor-specific API.

        Args:
            algorithm: Название алгоритма (catboost, lgbm, logreg, etc.).
            model_path: Директория с файлами модели.

        Returns:
            ``mlflow.models.model.ModelInfo`` или None если flavor не поддерживается.
        """
        try:
            if algorithm in ("catboost", "catboost_reg"):
                import catboost

                model_files = list(model_path.glob("*_prod.cbm"))
                if model_files:
                    cb_model = catboost.CatBoostClassifier()
                    cb_model.load_model(str(model_files[0]))
                    return mlflow.catboost.log_model(cb_model, artifact_path="model")

            elif algorithm in ("lgbm", "lgbm_reg"):
                import lightgbm as lgb

                model_files = list(model_path.glob("*_prod.txt"))
                if model_files:
                    lgb_model = lgb.Booster(model_file=str(model_files[0]))
                    return mlflow.lightgbm.log_model(lgb_model, artifact_path="model")

            elif algorithm == "logreg":
                import pickle

                model_files = list(model_path.glob("*_prod.pkl"))
                if model_files:
                    with model_files[0].open("rb") as f:
                        sk_model = pickle.load(f)  # noqa: S301
                    return mlflow.sklearn.log_model(sk_model, artifact_path="model")

        except Exception:
            logger.debug(
                "Flavor-specific log_model не удался для '%s'",
                algorithm,
                exc_info=True,
            )

        return None

    def _log_metrics_to_mlflow(
        self,
        shadow_metrics: dict[str, Any],
        test_metrics: dict[str, float],
        calibration_metrics: dict[str, Any],
        business_metrics: dict[str, Any],
        stability_metrics: dict[str, Any],
        optuna_metrics: dict[str, Any],
        feature_importance: pd.DataFrame | None,
        feature_selection_result: Any,
        cfg: DictConfig,
        feature_names: list[str],
        metrics_fs_fit: dict[str, Any] | None = None,
    ) -> None:
        """Залогировать все метрики в MLflow.

        Args:
            shadow_metrics: Метрики Shadow модели (TSCV).
            test_metrics: ML-метрики на test set.
            calibration_metrics: Метрики калибровки.
            business_metrics: Бизнес-метрики (BettingSimulator).
            stability_metrics: Анализ стабильности.
            optuna_metrics: Метрики Optuna оптимизации.
            feature_importance: DataFrame с важностью фичей.
            feature_selection_result: Результат отбора фичей.
            cfg: Конфигурация.
            feature_names: Список фичей.
            metrics_fs_fit: Если задан (после ``apply_selected_to_fit``), дополнительно
                логируются те же семейства метрик с префиксом ``*_fs_fit_*`` для сравнения.
        """
        # ── Параметры ────────────────────────────────────────────────
        mlflow.log_param("algorithm", cfg.algorithm.name)
        mlflow.log_param("model_target", cfg.algorithm.get("_target_", "unknown"))
        mlflow.log_param("featureset", cfg.features.name)
        mlflow.log_param("seed", cfg.seed)
        mlflow.log_param("n_features", len(feature_names))

        # Гиперпараметры модели
        if hasattr(cfg.algorithm, "params"):
            for key, value in cfg.algorithm.params.items():
                mlflow.log_param(f"model__{key}", value)

        # ── Shadow метрики (TSCV) — VALIDATED ────────────────────────
        mlflow.log_metric("shadow_logloss", shadow_metrics["logloss"])
        mlflow.log_metric("shadow_logloss_std", shadow_metrics["std_logloss"])
        mlflow.log_metric("shadow_auc", shadow_metrics["auc"])
        mlflow.log_metric("shadow_auc_std", shadow_metrics["std_auc"])
        mlflow.log_metric("shadow_accuracy", shadow_metrics["accuracy"])
        mlflow.log_metric("shadow_brier", shadow_metrics["brier"])
        mlflow.log_metric("shadow_ece", shadow_metrics["ece"])
        mlflow.log_metric("shadow_ece_std", shadow_metrics["std_ece"])
        mlflow.set_tag("shadow_validated", "true")

        # ── Test-set метрики (holdout) ───────────────────────────────
        for metric_name, value in test_metrics.items():
            mlflow.log_metric(f"test_{metric_name}", value)
        mlflow.set_tag("test_validated", "true")

        if metrics_fs_fit:
            mlflow.set_tag("fs_fit_applied", "true")
            tfs = metrics_fs_fit["test"]
            for metric_name, value in tfs.items():
                mlflow.log_metric(f"test_fs_fit_{metric_name}", value)
            sms = metrics_fs_fit["shadow"]
            mlflow.log_metric("shadow_fs_fit_logloss", sms["logloss"])
            mlflow.log_metric("shadow_fs_fit_logloss_std", sms["std_logloss"])
            mlflow.log_metric("shadow_fs_fit_auc", sms["auc"])
            mlflow.log_metric("shadow_fs_fit_auc_std", sms["std_auc"])
            mlflow.log_metric("shadow_fs_fit_accuracy", sms["accuracy"])
            mlflow.log_metric("shadow_fs_fit_brier", sms["brier"])
            mlflow.log_metric("shadow_fs_fit_ece", sms["ece"])
            mlflow.log_metric("shadow_fs_fit_ece_std", sms["std_ece"])
            fold_details_sf = sms.get("fold_details", {})
            if fold_details_sf:
                for key, value in fold_details_sf.items():
                    if key.startswith("fold_") and isinstance(value, (int, float)):
                        mlflow.log_metric(f"tscv_fs_fit_{key}", float(value))
        else:
            mlflow.set_tag("fs_fit_applied", "false")

        # ── Калибровка ───────────────────────────────────────────────
        if calibration_metrics:
            mlflow.log_metric("cal_ece_before", calibration_metrics["ece_before"])
            if calibration_metrics["ece_after"] is not None:
                mlflow.log_metric("cal_ece_after", calibration_metrics["ece_after"])
            mlflow.set_tag("is_calibrated", str(calibration_metrics["is_calibrated"]))
            mlflow.set_tag("calibration_method", calibration_metrics["method"])
            mlflow.log_param("calibration_threshold", calibration_metrics["threshold"])

        if metrics_fs_fit and metrics_fs_fit.get("calibration"):
            cm2 = metrics_fs_fit["calibration"]
            if cm2 and "ece_before" in cm2:
                mlflow.log_metric("cal_fs_fit_ece_before", cm2["ece_before"])
                if cm2.get("ece_after") is not None:
                    mlflow.log_metric("cal_fs_fit_ece_after", cm2["ece_after"])

        # ── Бизнес-метрики (BettingSimulator) ────────────────────────
        if business_metrics:
            self._log_business_metrics_to_mlflow(business_metrics)
        else:
            mlflow.set_tag("has_business_metrics", "false")

        if metrics_fs_fit and metrics_fs_fit.get("business"):
            bfs = metrics_fs_fit["business"]
            if bfs:
                self._log_business_metrics_to_mlflow(bfs, name_prefix="fs_fit_")

        # ── Стабильность ─────────────────────────────────────────────
        mlflow.log_metric("stability_cv_logloss", stability_metrics["cv_logloss"])
        mlflow.log_metric("stability_std_auc", stability_metrics["std_auc"])
        mlflow.set_tag("stability_level", stability_metrics["stability_level"])
        mlflow.set_tag("prod_confidence", stability_metrics["prod_confidence"])
        mlflow.set_tag("recommendation", stability_metrics["recommendation"])

        # ── Fold-level метрики (TSCV) ──────────────────────────────────
        fold_details = shadow_metrics.get("fold_details", {})
        if fold_details:
            for key, value in fold_details.items():
                if key.startswith("fold_") and isinstance(value, (int, float)):
                    mlflow.log_metric(f"tscv_{key}", float(value))

        # ── Optuna ────────────────────────────────────────────────────
        if optuna_metrics.get("enabled", False):
            mlflow.set_tag("hyper_optimized", "true")
            mlflow.set_tag("optuna_study", optuna_metrics.get("study_name", ""))
        else:
            mlflow.set_tag("hyper_optimized", "false")

        # ── Feature Importance ────────────────────────────────────────
        if feature_importance is not None and not feature_importance.empty:
            importance_csv = feature_importance.to_csv(index=False)
            mlflow.log_text(importance_csv, "feature_importance.csv")

            # Логируем top-10 фичей как метрики
            top_n = min(10, len(feature_importance))
            for idx in range(top_n):
                row = feature_importance.iloc[idx]
                feat_name = str(row["feature"])[:50]  # MLflow лимит
                mlflow.log_metric(
                    f"fi_top{idx + 1}",
                    float(row["importance"]),
                )
                mlflow.set_tag(f"fi_top{idx + 1}_name", feat_name)

        if metrics_fs_fit and metrics_fs_fit.get("feature_importance") is not None:
            fi2 = metrics_fs_fit["feature_importance"]
            if not fi2.empty:
                mlflow.log_text(
                    fi2.to_csv(index=False),
                    "feature_importance_fs_fit.csv",
                )

        # ── Feature Selection ────────────────────────────────────────
        if feature_selection_result is not None:
            mlflow.log_metric("fs_n_selected", feature_selection_result.n_selected)
            mlflow.log_metric("fs_n_total", feature_selection_result.n_total)
            mlflow.log_metric("fs_reduction_pct", feature_selection_result.reduction_pct)
            mlflow.set_tag("fs_strategy", feature_selection_result.strategy)
            mlflow.set_tag(
                "fs_methods",
                ",".join(feature_selection_result.metadata.get("methods", [])),
            )

            # Агрегированное ранжирование как артефакт
            if not feature_selection_result.aggregated_ranking.empty:
                ranking_csv = feature_selection_result.aggregated_ranking.to_csv(index=False)
                mlflow.log_text(ranking_csv, "feature_selection/aggregated_ranking.csv")

            # Отобранные фичи
            mlflow.log_text(
                "\n".join(feature_selection_result.selected_features),
                "feature_selection/selected_features.txt",
            )

            # Ранжирование каждого метода
            for method, ranking_result in feature_selection_result.rankings.items():
                method_csv = ranking_result.ranking.to_csv(index=False)
                mlflow.log_text(method_csv, f"feature_selection/{method}_ranking.csv")

            logger.info(
                "Feature Selection: %d → %d фичей (%.1f%% reduction)",
                feature_selection_result.n_total,
                feature_selection_result.n_selected,
                feature_selection_result.reduction_pct,
            )

        # ── Артефакты ────────────────────────────────────────────────
        mlflow.log_text("\n".join(feature_names), "features.txt")

        logger.info("Метрики залогированы в MLflow")
        logger.info("  Shadow (TSCV): validated=true")
        logger.info("  Test (holdout): validated=true")
        if calibration_metrics:
            logger.info(
                "  Calibration: ECE %.4f → %s",
                calibration_metrics["ece_before"],
                calibration_metrics["ece_after"]
                if calibration_metrics["ece_after"] is not None
                else "N/A",
            )
        if business_metrics:
            logger.info(
                "  Business: ROI=%.2f%%, bets=%d, sharpe=%.3f, PF=%.2f",
                business_metrics.get("roi", 0),
                business_metrics.get("n_bets", 0),
                business_metrics.get("sharpe_like", 0),
                business_metrics.get("profit_factor", 0),
            )
        if feature_importance is not None and not feature_importance.empty:
            logger.info(
                "  Feature importance: %d фичей залогировано",
                len(feature_importance),
            )
        if optuna_metrics.get("enabled", False):
            logger.info("  Optuna: hyper_optimized=true")
        logger.info(
            "  Stability: %s (confidence=%s)",
            stability_metrics["stability_level"],
            stability_metrics["prod_confidence"],
        )

    # ─────────────────────────────────────────────────────────────────────
    # BUSINESS METRICS MLflow LOGGING
    # ─────────────────────────────────────────────────────────────────────

    def _log_business_metrics_to_mlflow(
        self,
        bm: dict[str, Any],
        *,
        name_prefix: str = "",
    ) -> None:
        """Залогировать все бизнес-метрики и артефакты в MLflow.

        Args:
            bm: Словарь бизнес-метрик из ``_compute_business_metrics``.
            name_prefix: Префикс имён метрик/артефактов (например ``fs_fit_`` для сравнения
                с прогоном на полном наборе фичей при ``apply_selected_to_fit``).
        """
        import json

        p = name_prefix
        if not p:
            mlflow.set_tag("has_business_metrics", "true")
            mlflow.set_tag("odds_column", bm["odds_column"])
            mlflow.log_param("betting_valid_odds", bm["valid_odds_count"])

        # ── Volume ───────────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_n_bets", bm["n_bets"])
        mlflow.log_metric(f"{p}betting_turnover_units", bm["turnover_units"])
        mlflow.log_metric(f"{p}betting_coverage", bm["coverage"])
        mlflow.log_metric(f"{p}betting_n_total_events", bm["n_total_events"])

        # ── Profit ───────────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_profit_units", bm["profit_units"])
        mlflow.log_metric(f"{p}betting_roi", bm["roi"])
        mlflow.log_metric(f"{p}betting_avg_profit_per_bet", bm["avg_profit_per_bet"])

        # ── Edge / EV ────────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_avg_edge", bm["avg_edge"])
        mlflow.log_metric(f"{p}betting_avg_ev", bm["avg_ev"])
        mlflow.log_metric(f"{p}betting_ev_sum_units", bm["ev_sum_units"])
        mlflow.log_metric(f"{p}betting_ev_realization", bm["ev_realization"])

        # ── Win / Loss ───────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_hit_rate", bm["hit_rate"])
        mlflow.log_metric(f"{p}betting_num_wins", bm["num_wins"])

        # ── Risk ─────────────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_max_drawdown_units", bm["max_drawdown_units"])
        mlflow.log_metric(f"{p}betting_max_drawdown_pct", bm["max_drawdown_pct"])
        mlflow.log_metric(f"{p}betting_std_return_per_bet", bm["std_return_per_bet"])
        mlflow.log_metric(f"{p}betting_sharpe_like", bm["sharpe_like"])
        mlflow.log_metric(f"{p}betting_profit_factor", bm["profit_factor"])

        # ── Averages ─────────────────────────────────────────────────
        mlflow.log_metric(f"{p}betting_avg_odds", bm["avg_odds"])

        # ── Calibration on selected ──────────────────────────────────
        for key in ("cal_selected_brier", "cal_selected_logloss", "cal_selected_ece"):
            if key in bm:
                mlflow.log_metric(f"{p}{key}", bm[key])

        # ── Odds-bin metrics ─────────────────────────────────────────
        odds_bins: dict[str, dict[str, float]] = bm.get("odds_bin_metrics", {})
        for bin_label, bin_data in odds_bins.items():
            for metric_name, value in bin_data.items():
                mlflow.log_metric(
                    f"{p}betting_{metric_name}_odds_{bin_label}",
                    value,
                )

        # ── Threshold sweep (artifact) ───────────────────────────────
        sweep_df: pd.DataFrame | None = bm.get("sweep_df")
        if sweep_df is not None and not sweep_df.empty:
            sweep_csv = sweep_df.to_csv(index=False)
            sweep_name = f"{p}threshold_sweep.csv" if p else "threshold_sweep.csv"
            mlflow.log_text(sweep_csv, sweep_name)

            # Логируем ключевые пороги как отдельные метрики
            key_thresholds = [0.0, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
            for _, row in sweep_df.iterrows():
                thr = row["threshold"]
                if thr in key_thresholds:
                    suffix = str(thr).replace(".", "_")
                    mlflow.log_metric(f"{p}sweep_n_bets_thr_{suffix}", row["n_bets"])
                    mlflow.log_metric(f"{p}sweep_roi_thr_{suffix}", row["roi"])
                    mlflow.log_metric(f"{p}sweep_profit_thr_{suffix}", row["profit_units"])
                    if abs(row["ev_realization"]) < 1e6:  # Защита от inf
                        mlflow.log_metric(
                            f"{p}sweep_ev_real_thr_{suffix}",
                            row["ev_realization"],
                        )

        # ── Equity curve (artifact) ──────────────────────────────────
        equity_curve: list[float] = bm.get("equity_curve", [])
        if equity_curve:
            equity_df = pd.DataFrame({"step": range(len(equity_curve)), "bankroll": equity_curve})
            eq_name = f"{p}equity_curve.csv" if p else "equity_curve.csv"
            mlflow.log_text(equity_df.to_csv(index=False), eq_name)

        # ── Calibration table (reliability diagram data) ─────────────
        cal_table: list[dict[str, float]] = bm.get("cal_table", [])
        if cal_table:
            cal_name = f"{p}calibration_table.json" if p else "calibration_table.json"
            mlflow.log_text(
                json.dumps(cal_table, indent=2, default=str),
                cal_name,
            )
