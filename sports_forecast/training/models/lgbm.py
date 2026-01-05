"""
LightGBM модель с поддержкой TSCV, Optuna, калибровки.

Быстрая альтернатива CatBoost для экспериментов.
Поддерживает:
- Categorical features (через category dtype)
- Early stopping
- Feature importance

Примеры:
    >>> lgbm = LGBMModel(name="lgbm", config=cfg)
    >>> lgbm.fit(X_train, y_train, eval_set=(X_val, y_val))
    >>> proba = lgbm.predict_proba(X_test)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from lightgbm import LGBMClassifier
from omegaconf import DictConfig

from sports_forecast.training.base import BaseSingleModel
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class LGBMModel(BaseSingleModel):
    """
    LightGBM модель для бинарной классификации.

    Использует LGBMClassifier с поддержкой:
    - Categorical features (через category dtype или индексы)
    - Early stopping
    - Feature importance
    - Быстрое обучение

    Args:
        name: Название модели (по умолчанию "lgbm").
        config: Конфигурация модели из Hydra.
        params: Гиперпараметры LightGBM.

    Attributes:
        model_: LGBMClassifier.
        cat_features_: Список категориальных фичей.

    Examples:
        >>> lgbm = LGBMModel(name="lgbm", config=cfg.model)
        >>> lgbm.fit(X_train, y_train, eval_set=[(X_val, y_val)])
        >>> proba = lgbm.predict_proba(X_test)
    """

    def __init__(
        self,
        name: str = "lgbm",
        config: DictConfig | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        """
        Инициализация LightGBM модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
            params: Гиперпараметры LightGBM.
        """
        # Параметры по умолчанию для LightGBM
        default_params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "n_estimators": 500,
            "learning_rate": 0.1,
            "max_depth": 7,
            "num_leaves": 31,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.0,
            "reg_lambda": 0.0,
            "random_state": 777,
            "verbose": -1,  # Отключаем логирование LightGBM
        }

        if params is None and config is not None and hasattr(config, "params"):
            params = dict(config.params)
        elif params is None:
            params = default_params
        else:
            params = {**default_params, **params}

        super().__init__(name=name, config=config or {}, params=params)

        logger.info("Инициализирован LGBMModel с параметрами: %s", self.params)

    def _create_model(self) -> LGBMClassifier:
        """
        Создать экземпляр LGBMClassifier.

        Returns:
            Экземпляр LGBMClassifier с параметрами из self.params.
        """
        return LGBMClassifier(**self.params)

    def _fit_implementation(
        self,
        X: pd.DataFrame,  # noqa: N803
        y: pd.Series,
        **fit_kwargs,
    ) -> None:
        """
        Обучить LightGBM модель.

        Args:
            X: Фичи для обучения.
            y: Таргет.
            **fit_kwargs: Дополнительные параметры:
                - eval_set: List[Tuple[X_val, y_val]] для валидации.
                - categorical_feature: Список категориальных фичей или 'auto'.
                - callbacks: Список callbacks (early_stopping, log_evaluation).

        Examples:
            >>> model._fit_implementation(
            ...     X_train, y_train,
            ...     eval_set=[(X_val, y_val)],
            ...     callbacks=[lgb.early_stopping(30)],
            ... )
        """
        # Категориальные фичи
        if "categorical_feature" not in fit_kwargs and self.cat_features_:
            fit_kwargs["categorical_feature"] = self.cat_features_

        # Обучение
        logger.info("Начинаю обучение LightGBM...")
        self.model_.fit(X, y, **fit_kwargs)

        logger.info("LightGBM обучен: %d деревьев", self.model_.n_estimators)

    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить LightGBM модель.

        Args:
            path: Путь для сохранения (без расширения).
            version: Версия модели ('shadow' или 'prod').

        Examples:
            >>> model.save(Path("models/uel_kz_1/is_win"), version="shadow")
            >>> # Сохранено в: models/uel_kz_1/is_win_shadow.txt
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Сохранять нечего.")

        if version not in ["shadow", "prod"]:
            raise ValueError(f"Версия должна быть 'shadow' или 'prod', получено: {version}")

        # LightGBM использует расширение .txt
        save_path = path.parent / f"{path.stem}_{version}.txt"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Сохранение
        self.model_.booster_.save_model(str(save_path))
        logger.info("LightGBM модель '%s' (%s) сохранена: %s", self.name, version, save_path)

    def load(self, path: Path) -> LGBMModel:
        """
        Загрузить LightGBM модель.

        Args:
            path: Путь к файлу модели (.txt).

        Returns:
            self: Для chaining.

        Examples:
            >>> model.load(Path("models/uel_kz_1/is_win_shadow.txt"))
        """
        if not path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {path}")

        # Создаём модель если ещё не создана
        if self.model_ is None:
            self.model_ = self._create_model()

        # Загрузка через booster
        import lightgbm as lgb

        booster = lgb.Booster(model_file=str(path))
        self.model_._Booster = booster
        self.is_fitted_ = True

        logger.info("LightGBM модель '%s' загружена из: %s", self.name, path)
        return self

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Получить важность фичей из LightGBM.

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

        importances = self.model_.feature_importances_
        feature_names = self.model_.feature_name_

        return (
            pd.DataFrame(
                {
                    "feature": feature_names,
                    "importance": importances,
                }
            )
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )
