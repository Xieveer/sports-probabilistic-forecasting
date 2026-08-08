"""
Stacking Ensemble с мета-моделью.

Обучает базовые модели через TSCV и собирает out-of-fold предсказания
для обучения мета-модели (обычно LogisticRegression).

Процесс:
1. Базовые модели обучаются на TSCV фолдах
2. Собираются out-of-fold предсказания
3. Мета-модель обучается на этих предсказаниях
4. Итоговое предсказание = мета-модель(базовые_предсказания)

Примеры:
    >>> stacking = StackingEnsemble(
    ...     base_models=[catboost, lgbm, logreg],
    ...     meta_model=logreg_meta,
    ... )
    >>> stacking.fit(train_features, train_target)
    >>> proba = stacking.predict_proba(test_features)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from omegaconf import DictConfig

from sports_forecast.training.base import BaseModel, BaseSingleModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class StackingEnsemble(BaseModel):
    """
    Stacking Ensemble с мета-моделью.

    Архитектура:
    - Базовые модели: CatBoost, LightGBM, LogReg (обучаются через TSCV)
    - Мета-модель: LogisticRegression (обучается на out-of-fold предсказаниях)

    Args:
        name: Название ансамбля (по умолчанию "stacking").
        base_models: Список базовых моделей (экземпляры BaseSingleModel).
        meta_model: Мета-модель (экземпляр BaseSingleModel).
        config: Конфигурация ансамбля из Hydra.
        n_splits: Количество фолдов TSCV для базовых моделей (по умолчанию 4).

    Attributes:
        base_models: Список базовых моделей.
        meta_model: Мета-модель.
        n_splits: Количество фолдов TSCV.

    Examples:
        >>> from sports_forecast.training.models import CatBoostModel, LGBMModel, LogRegModel
        >>>
        >>> stacking = StackingEnsemble(
        ...     name="stacking_win",
        ...     base_models=[
        ...         CatBoostModel("catboost"),
        ...         LGBMModel("lgbm"),
        ...         LogRegModel("logreg"),
        ...     ],
        ...     meta_model=LogRegModel("meta"),
        ... )
        >>> stacking.fit(train_features, train_target)
        >>> proba = stacking.predict_proba(test_features)
    """

    def __init__(
        self,
        name: str = "stacking",
        base_models: list[BaseSingleModel] | None = None,
        meta_model: BaseSingleModel | None = None,
        config: DictConfig | dict[str, Any] | None = None,
        n_splits: int = 4,
    ):
        """
        Инициализация Stacking Ensemble.

        Args:
            name: Название ансамбля.
            base_models: Список базовых моделей.
            meta_model: Мета-модель.
            config: Конфигурация ансамбля.
            n_splits: Количество фолдов TSCV.

        Raises:
            ValueError: Если base_models или meta_model не указаны.
        """
        super().__init__(name=name, config=config or {})

        if base_models is None or len(base_models) == 0:
            raise ValueError("base_models должен содержать хотя бы одну модель")

        if meta_model is None:
            raise ValueError("meta_model должен быть указан")

        self.base_models = base_models
        self.meta_model = meta_model
        self.n_splits = n_splits

        # TSCV для базовых моделей
        self.tscv = TimeSeriesCrossValidator(n_splits=n_splits)

        logger.info(
            "Инициализирован StackingEnsemble '%s': %d базовых моделей + мета-модель",
            name,
            len(base_models),
        )
        for base_model in base_models:
            logger.info("  - Базовая модель: %s", base_model.get_name())
        logger.info("  - Мета-модель: %s", meta_model.get_name())

    def fit(self, features: pd.DataFrame, target: pd.Series, **kwargs) -> StackingEnsemble:
        """
        Обучить Stacking Ensemble.

        Процесс:
        1. Для каждой базовой модели:
           - Обучение на TSCV фолдах
           - Сбор out-of-fold предсказаний
        2. Обучение мета-модели на out-of-fold предсказаниях

        Args:
            features: Фичи для обучения.
            target: Таргет.
            **kwargs: Дополнительные параметры (игнорируются).

        Returns:
            self: Для chaining.

        Examples:
            >>> stacking.fit(train_features, train_target)
        """
        logger.info("=" * 60)
        logger.info("ОБУЧЕНИЕ STACKING ENSEMBLE: %s", self.name)
        logger.info("Базовых моделей: %d", len(self.base_models))
        logger.info("TSCV фолдов: %d", self.n_splits)
        logger.info("=" * 60)

        n_samples = len(features)

        # Матрица для out-of-fold предсказаний
        # Shape: (n_samples, n_base_models)
        oof_predictions = [[0.0] * len(self.base_models) for _ in range(n_samples)]

        # Обучаем базовые модели через TSCV
        for model_idx, base_model in enumerate(self.base_models):
            logger.info(
                "--- Базовая модель %d/%d: %s ---",
                model_idx + 1,
                len(self.base_models),
                base_model.get_name(),
            )

            # Out-of-fold предсказания для этой модели
            oof_model = [0.0] * n_samples

            # TSCV
            for fold_idx, (train_idx, val_idx) in enumerate(self.tscv.split(features, target), 1):
                logger.info("  Фолд %d/%d...", fold_idx, self.n_splits)

                # Разбиваем данные
                train_features = features.iloc[train_idx]
                val_features = features.iloc[val_idx]
                train_target = target.iloc[train_idx]

                # Обучаем базовую модель на фолде
                base_model.fit(train_features, train_target)

                # Предсказания на val (out-of-fold)
                proba_val = base_model.predict_proba(val_features)[:, 1]

                # Сохраняем в oof_model
                for row_idx, probability in zip(val_idx.tolist(), proba_val.tolist(), strict=True):
                    oof_model[int(row_idx)] = float(probability)

            # Сохраняем в матрицу oof_predictions
            for row_idx, probability in enumerate(oof_model):
                oof_predictions[row_idx][model_idx] = probability

            logger.info("  ✓ Out-of-fold предсказания собраны для %s", base_model.get_name())

            # Теперь обучаем базовую модель на ВСЕХ данных (для prod)
            logger.info("  Обучаю %s на всех данных (prod)...", base_model.get_name())
            base_model.fit(features, target)
            logger.info("  ✓ %s обучена на всех данных", base_model.get_name())

        logger.info("=" * 60)
        logger.info("ВСЕ БАЗОВЫЕ МОДЕЛИ ОБУЧЕНЫ")
        logger.info("=" * 60)

        # Создаём DataFrame для мета-модели
        meta_features = pd.DataFrame(
            oof_predictions,
            columns=[f"model_{model.get_name()}" for model in self.base_models],
        )

        # Обучаем мета-модель
        logger.info(
            "Обучаю мета-модель '%s' на out-of-fold предсказаниях...", self.meta_model.get_name()
        )
        self.meta_model.fit(meta_features, target)

        self.is_fitted_ = True

        logger.info("=" * 60)
        logger.info("✓ STACKING ENSEMBLE ОБУЧЕН")
        logger.info("=" * 60)

        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """
        Предсказать вероятности через Stacking Ensemble.

        Процесс:
        1. Получить предсказания от базовых моделей
        2. Передать их в мета-модель
        3. Вернуть итоговые вероятности

        Args:
            features: Фичи для предсказания.

        Returns:
            Массив вероятностей shape (n_samples, 2).

        Raises:
            ValueError: Если ансамбль не обучен.

        Examples:
            >>> proba = stacking.predict_proba(test_features)
            >>> proba[:, 1]  # Вероятность класса 1
        """
        if not self.is_fitted_:
            raise ValueError(
                f"Ансамбль '{self.name}' не обучен. Вызовите fit() перед predict_proba()"
            )

        # Получаем предсказания от базовых моделей
        base_predictions = [[0.0] * len(self.base_models) for _ in range(len(features))]

        for model_idx, base_model in enumerate(self.base_models):
            proba = base_model.predict_proba(features)[:, 1]
            for row_idx, probability in enumerate(proba.tolist()):
                base_predictions[row_idx][model_idx] = float(probability)

        # Создаём DataFrame для мета-модели
        meta_features = pd.DataFrame(
            base_predictions,
            columns=[f"model_{model.get_name()}" for model in self.base_models],
        )

        # Предсказания мета-модели
        return self.meta_model.predict_proba(meta_features)

    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить Stacking Ensemble (базовые + мета модели).

        Args:
            path: Путь для сохранения (директория).
            version: Версия модели ('shadow' или 'prod').

        Examples:
            >>> stacking.save(Path("models/uel_kz_1/stacking_win"), version="shadow")
            >>> # Сохранено в:
            >>> # models/uel_kz_1/stacking_win_shadow/
            >>> #   catboost.cbm
            >>> #   lgbm.txt
            >>> #   logreg.pkl
            >>> #   meta.pkl
        """
        if not self.is_fitted_:
            raise ValueError(f"Ансамбль '{self.name}' не обучен. Сохранять нечего.")

        if version not in ["shadow", "prod"]:
            raise ValueError(f"Версия должна быть 'shadow' или 'prod', получено: {version}")

        # Создаём директорию для ансамбля
        save_dir = path.parent / f"{path.name}_{version}"
        save_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Сохраняю Stacking Ensemble '%s' (%s) в: %s", self.name, version, save_dir)

        # Сохраняем базовые модели
        for base_model in self.base_models:
            model_path = save_dir / base_model.get_name()
            base_model.save(model_path, version="prod")  # Базовые модели - всегда prod

        # Сохраняем мета-модель
        meta_path = save_dir / "meta"
        self.meta_model.save(meta_path, version="prod")

        logger.info("✓ Stacking Ensemble '%s' (%s) сохранен", self.name, version)

    def load(self, path: Path) -> StackingEnsemble:
        """
        Загрузить Stacking Ensemble.

        Args:
            path: Путь к директории ансамбля.

        Returns:
            self: Для chaining.

        Examples:
            >>> stacking.load(Path("models/uel_kz_1/stacking_win_shadow"))
        """
        if not path.exists():
            raise FileNotFoundError(f"Директория ансамбля не найдена: {path}")

        logger.info("Загружаю Stacking Ensemble '%s' из: %s", self.name, path)

        # Загружаем базовые модели
        for base_model in self.base_models:
            model_dir = path / base_model.get_name()
            if not model_dir.exists() or not model_dir.is_dir():
                raise FileNotFoundError(
                    f"Директория базовой модели '{base_model.get_name()}' не найдена в {path}"
                )

            # Ищем файл модели внутри поддиректории (расширение зависит от типа).
            # Исключаем вспомогательные файлы (preprocessor, calibration).
            model_files = [
                f
                for f in model_dir.iterdir()
                if f.is_file()
                and "_prod" in f.stem
                and "_preprocessor" not in f.stem
                and "_calibration" not in f.stem
            ]
            if not model_files:
                raise FileNotFoundError(
                    f"Файл базовой модели '{base_model.get_name()}' не найден в {model_dir}"
                )

            base_model.load(model_files[0])

        # Загружаем мета-модель
        meta_dir = path / "meta"
        if not meta_dir.exists() or not meta_dir.is_dir():
            raise FileNotFoundError(f"Директория мета-модели не найдена в {path}")

        meta_files = [
            f
            for f in meta_dir.iterdir()
            if f.is_file()
            and "_prod" in f.stem
            and "_preprocessor" not in f.stem
            and "_calibration" not in f.stem
        ]
        if not meta_files:
            raise FileNotFoundError(f"Файл мета-модели не найден в {meta_dir}")

        self.meta_model.load(meta_files[0])

        self.is_fitted_ = True

        logger.info("✓ Stacking Ensemble '%s' загружен", self.name)

        return self
