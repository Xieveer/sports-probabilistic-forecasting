"""
CatBoost модель с поддержкой TSCV, Optuna, калибровки.

Основная модель проекта для классификации.
Поддерживает:
- Categorical features (автоматическое определение)
- Early stopping
- Eval set для валидации
- Feature importance

Примеры:
    >>> catboost = CatBoostModel(name="catboost", config=cfg)
    >>> catboost.fit(X_train, y_train, eval_set=(X_val, y_val))
    >>> proba = catboost.predict_proba(X_test)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig

from sports_forecast.training.base import BaseSingleModel
from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


class CatBoostModel(BaseSingleModel):
    """
    CatBoost модель для бинарной классификации.

    Использует CatBoostClassifier с поддержкой:
    - Categorical features (автоматически определяются по dtype='object')
    - Early stopping на eval_set
    - Feature importance
    - Сохранение/загрузка модели

    Args:
        name: Название модели (по умолчанию "catboost").
        config: Конфигурация модели из Hydra.
        params: Гиперпараметры CatBoost.

    Attributes:
        model_: CatBoostClassifier.
        cat_features_: Список категориальных фичей.

    Examples:
        >>> catboost = CatBoostModel(name="catboost", config=cfg.model)
        >>> catboost.fit(
        ...     X_train, y_train,
        ...     eval_set=(X_val, y_val),
        ...     early_stopping_rounds=30,
        ...     use_best_model=True,
        ... )
        >>> proba = catboost.predict_proba(X_test)
    """

    def __init__(
        self,
        name: str = "catboost",
        config: DictConfig | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        """
        Инициализация CatBoost модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
            params: Гиперпараметры CatBoost
                (iterations, learning_rate, depth, l2_leaf_reg, etc.).
        """
        # Параметры по умолчанию для CatBoost
        default_params = {
            "loss_function": "Logloss",
            "eval_metric": "Logloss",
            "iterations": 500,
            "learning_rate": 0.1,
            "depth": 6,
            "l2_leaf_reg": 3,
            "random_seed": 777,
            "verbose": False,  # Логирование через logger
        }

        if params is None and config is not None and hasattr(config, "params"):
            params = dict(config.params)
        elif params is None:
            params = default_params
        else:
            # Объединяем с defaults
            params = {**default_params, **params}

        super().__init__(name=name, config=config or {}, params=params)

        logger.info("Инициализирован CatBoostModel с параметрами: %s", self.params)

    def _create_model(self) -> CatBoostClassifier:
        """
        Создать экземпляр CatBoostClassifier.

        Returns:
            Экземпляр CatBoostClassifier с параметрами из self.params.
        """
        return CatBoostClassifier(**self.params)

    def _fit_implementation(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        **fit_kwargs,
    ) -> None:
        """
        Обучить CatBoost модель.

        Args:
            X: Фичи для обучения.
            y: Таргет.
            **fit_kwargs: Дополнительные параметры:
                - eval_set: Tuple[X_val, y_val] для валидации.
                - cat_features: Список категориальных фичей.
                - early_stopping_rounds: Количество итераций без улучшения.
                - use_best_model: Использовать лучшую модель по eval_set.
                - verbose: Частота логирования (если True, каждые 100 итераций).

        Examples:
            >>> model._fit_implementation(
            ...     X_train, y_train,
            ...     eval_set=(X_val, y_val),
            ...     early_stopping_rounds=30,
            ... )
        """
        # Настройка verbose (если не указан явно)
        if "verbose" not in fit_kwargs and self.params.get("verbose") is False:
            # Логируем каждые 100 итераций
            fit_kwargs["verbose"] = 100

        # Обучение
        logger.info("Начинаю обучение CatBoost...")
        self.model_.fit(X, y, **fit_kwargs)

        logger.info("CatBoost обучен: %d итераций", self.model_.tree_count_)

        # Если использовался early stopping, логируем лучшую итерацию
        if "eval_set" in fit_kwargs and fit_kwargs.get("use_best_model", True):
            best_iter = self.model_.get_best_iteration()
            if best_iter is not None:
                logger.info("Лучшая итерация: %d (early stopping)", best_iter)

    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить CatBoost модель.

        Args:
            path: Путь для сохранения (без расширения).
            version: Версия модели ('shadow' или 'prod').

        Examples:
            >>> model.save(Path("models/uel_kz_1/is_win"), version="shadow")
            >>> # Сохранено в: models/uel_kz_1/is_win_shadow.cbm
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Сохранять нечего.")

        # Добавляем версию к имени файла
        if version not in ["shadow", "prod"]:
            raise ValueError(f"Версия должна быть 'shadow' или 'prod', получено: {version}")

        # CatBoost использует расширение .cbm
        save_path = path.parent / f"{path.stem}_{version}.cbm"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Сохранение
        self.model_.save_model(str(save_path))
        logger.info("CatBoost модель '%s' (%s) сохранена: %s", self.name, version, save_path)

    def load(self, path: Path) -> CatBoostModel:
        """
        Загрузить CatBoost модель.

        Args:
            path: Путь к файлу модели (.cbm).

        Returns:
            self: Для chaining.

        Examples:
            >>> model.load(Path("models/uel_kz_1/is_win_shadow.cbm"))
        """
        if not path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {path}")

        # Создаём модель если ещё не создана
        if self.model_ is None:
            self.model_ = self._create_model()

        # Загрузка
        self.model_.load_model(str(path))
        self.is_fitted_ = True

        logger.info("CatBoost модель '%s' загружена из: %s", self.name, path)
        return self

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Получить важность фичей из CatBoost.

        Returns:
            DataFrame с колонками ['feature', 'importance'],
            отсортированный по убыванию важности.

        Raises:
            ValueError: Если модель не обучена.

        Examples:
            >>> importance = model.get_feature_importance()
            >>> print(importance.head(10))  # Топ-10 фичей
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Важность фичей недоступна.")

        importances = self.model_.get_feature_importance()
        feature_names = self.model_.feature_names_

        return pd.DataFrame(
            {
                "feature": feature_names,
                "importance": importances,
            }
        ).sort_values("importance", ascending=False).reset_index(drop=True)

