"""
Optuna оптимизатор для подбора гиперпараметров моделей.

Поддерживает:
- Оптимизацию на TSCV (усреднённый log loss по фолдам)
- Сохранение лучших параметров
- SQLite storage для персистентности
- Pruning для ускорения поиска

Примеры:
    >>> optimizer = OptunaOptimizer(model_name="catboost", tournament="uel_kz_1")
    >>> best_params = optimizer.optimize(
    ...     model=catboost_model,
    ...     X_train=X_train,
    ...     y_train=y_train,
    ...     n_trials=50,
    ... )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import optuna
from omegaconf import DictConfig, OmegaConf

from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


class OptunaOptimizer:
    """
    Optuna оптимизатор для подбора гиперпараметров.

    Использует TSCV для оценки качества гиперпараметров.
    Objective: минимизация среднего log loss по фолдам.

    Args:
        model_name: Название модели (для хранения study).
        tournament: Название турнира (для хранения study).
        storage_dir: Директория для SQLite хранилища (по умолчанию "optuna").
        n_splits: Количество фолдов TSCV (по умолчанию 4).

    Attributes:
        model_name: Название модели.
        tournament: Название турнира.
        study_name: Уникальное название study.
        storage_url: URL SQLite хранилища.
        tscv: TimeSeriesCrossValidator.

    Examples:
        >>> optimizer = OptunaOptimizer("catboost", "uel_kz_1")
        >>> best_params = optimizer.optimize(model, X_train, y_train, n_trials=30)
    """

    def __init__(
        self,
        model_name: str,
        tournament: str,
        storage_dir: Path | str = "optuna",
        n_splits: int = 4,
    ):
        """
        Инициализация Optuna оптимизатора.

        Args:
            model_name: Название модели.
            tournament: Название турнира.
            storage_dir: Директория для SQLite хранилища.
            n_splits: Количество фолдов TSCV.
        """
        self.model_name = model_name
        self.tournament = tournament
        self.study_name = f"{tournament}_{model_name}"
        self.n_splits = n_splits

        # SQLite storage для персистентности
        storage_path = Path(storage_dir)
        storage_path.mkdir(parents=True, exist_ok=True)
        self.storage_url = f"sqlite:///{storage_path}/{tournament}.db"

        # TSCV для оценки
        self.tscv = TimeSeriesCrossValidator(n_splits=n_splits)

        logger.info(
            "Инициализирован OptunaOptimizer: study='%s', storage=%s",
            self.study_name,
            self.storage_url,
        )

    def optimize(
        self,
        model: Any,
        X_train: Any,
        y_train: Any,
        param_space: Callable[[optuna.Trial], dict[str, Any]] | None = None,
        n_trials: int = 30,
        timeout: int | None = None,
        direction: str = "minimize",
    ) -> dict[str, Any]:
        """
        Оптимизировать гиперпараметры модели через Optuna.

        Args:
            model: Модель с методом fit() и predict_proba().
            X_train: Фичи для обучения.
            y_train: Таргет.
            param_space: Функция для генерации пространства параметров
                (trial -> dict). Если None, используется дефолтное
                пространство для модели.
            n_trials: Количество trial'ов.
            timeout: Максимальное время оптимизации в секундах.
            direction: Направление оптимизации ("minimize" или "maximize").

        Returns:
            Словарь с лучшими параметрами.

        Examples:
            >>> def param_space(trial):
            ...     return {
            ...         'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
            ...         'depth': trial.suggest_int('depth', 4, 12),
            ...     }
            >>> best_params = optimizer.optimize(model, X, y, param_space, n_trials=50)
        """
        logger.info("=" * 60)
        logger.info("OPTUNA ОПТИМИЗАЦИЯ")
        logger.info("Model: %s", self.model_name)
        logger.info("Tournament: %s", self.tournament)
        logger.info("N trials: %d", n_trials)
        logger.info("TSCV splits: %d", self.n_splits)
        logger.info("=" * 60)

        # Создаём или загружаем study
        study = optuna.create_study(
            study_name=self.study_name,
            storage=self.storage_url,
            load_if_exists=True,
            direction=direction,
        )

        # Пространство параметров
        if param_space is None:
            param_space = self._get_default_param_space(self.model_name)

        # Objective function
        def objective(trial: optuna.Trial) -> float:
            # Генерируем параметры
            params = param_space(trial)

            # Обновляем параметры модели
            model.params = params

            # Пересоздаём модель с новыми параметрами
            model.model_ = model._create_model()

            # Оценка через TSCV
            try:
                results = self.tscv.cross_validate(
                    model=model,
                    X=X_train,
                    y=y_train,
                    fit_kwargs={},
                )

                # Возвращаем средний log loss
                return float(results.get("mean_logloss", 1e6))

            except Exception as e:
                logger.error("Trial %d failed: %s", trial.number, e)
                # Возвращаем большое значение при ошибке
                return 1e6

        # Оптимизация
        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            show_progress_bar=True,
        )

        logger.info("=" * 60)
        logger.info("OPTUNA ЗАВЕРШЕНА")
        logger.info("Best value: %.4f", study.best_value)
        logger.info("Best params: %s", study.best_params)
        logger.info("=" * 60)

        return dict(study.best_params)

    def _get_default_param_space(
        self,
        model_name: str,
    ) -> Callable[[optuna.Trial], dict[str, Any]]:
        """
        Получить дефолтное пространство параметров для модели.

        Args:
            model_name: Название модели.

        Returns:
            Функция для генерации пространства параметров.

        Raises:
            ValueError: Если модель не поддерживается.
        """
        if model_name == "catboost":
            return self._catboost_param_space
        elif model_name == "lgbm" or model_name == "lightgbm":
            return self._lgbm_param_space
        elif model_name == "logreg" or model_name == "logistic":
            return self._logreg_param_space
        else:
            raise ValueError(
                f"Дефолтное пространство параметров для '{model_name}' не определено. "
                f"Передайте param_space явно в optimize()."
            )

    @staticmethod
    def _catboost_param_space(trial: optuna.Trial) -> dict[str, Any]:
        """
        Пространство параметров для CatBoost.

        Args:
            trial: Optuna trial.

        Returns:
            Словарь параметров для CatBoost.
        """
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "depth": trial.suggest_int("depth", 4, 12),
            "l2_leaf_reg": trial.suggest_int("l2_leaf_reg", 1, 10),
            "iterations": trial.suggest_int("iterations", 100, 1000),
            "loss_function": "Logloss",
            "eval_metric": "Logloss",
            "random_seed": 777,
            "verbose": False,
        }

    @staticmethod
    def _lgbm_param_space(trial: optuna.Trial) -> dict[str, Any]:
        """
        Пространство параметров для LightGBM.

        Args:
            trial: Optuna trial.

        Returns:
            Словарь параметров для LightGBM.
        """
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "num_leaves": trial.suggest_int("num_leaves", 20, 150),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            "random_state": 777,
            "verbose": -1,
        }

    @staticmethod
    def _logreg_param_space(trial: optuna.Trial) -> dict[str, Any]:
        """
        Пространство параметров для LogisticRegression.

        Args:
            trial: Optuna trial.

        Returns:
            Словарь параметров для LogisticRegression.
        """
        return {
            "C": trial.suggest_float("C", 1e-4, 100.0, log=True),
            "penalty": trial.suggest_categorical("penalty", ["l1", "l2"]),
            "solver": "saga",  # Поддерживает и l1, и l2
            "max_iter": 1000,
            "random_state": 777,
        }

    def save_best_params(self, save_path: Path) -> None:
        """
        Сохранить лучшие параметры из study в JSON.

        Args:
            save_path: Путь для сохранения JSON файла.

        Examples:
            >>> optimizer.save_best_params(Path("optuna/uel_kz_1_catboost_best.json"))
        """
        # Загружаем study
        study = optuna.load_study(
            study_name=self.study_name,
            storage=self.storage_url,
        )

        # Сохраняем лучшие параметры
        best_params = {
            "model_name": self.model_name,
            "tournament": self.tournament,
            "best_value": study.best_value,
            "best_params": study.best_params,
            "n_trials": len(study.trials),
        }

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", encoding="utf-8") as f:
            json.dump(best_params, f, indent=2, ensure_ascii=False)

        logger.info("Лучшие параметры сохранены: %s", save_path)

    def load_best_params(self, load_path: Path) -> dict[str, Any]:
        """
        Загрузить лучшие параметры из JSON.

        Args:
            load_path: Путь к JSON файлу.

        Returns:
            Словарь с лучшими параметрами.

        Examples:
            >>> best_params = optimizer.load_best_params(Path("optuna/uel_kz_1_catboost_best.json"))
        """
        with load_path.open(encoding="utf-8") as f:
            data = json.load(f)

        logger.info("Лучшие параметры загружены из: %s", load_path)
        return dict(data["best_params"])

