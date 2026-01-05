"""
Модуль обучения моделей с поддержкой TSCV, Optuna, ансамблей и калибровки.

Основные компоненты:
    - BaseModel: Базовый класс для всех моделей
    - BaseSingleModel: Базовый класс для одиночных моделей
    - BaseEnsembleModel: Базовый класс для ансамблей
    - ModelTrainer: Оркестратор обучения
    - TimeSeriesCrossValidator: TSCV для временных рядов
    - OptunaOptimizer: Оптимизация гиперпараметров
    - ModelCalibrator: Калибровка моделей

Примеры:
    >>> from sports_forecast.training import ModelTrainer
    >>> trainer = ModelTrainer(cfg)
    >>> trainer.train_single("catboost", "uel_kz_1", "is_win")
"""

from sports_forecast.training.base import BaseModel, BaseSingleModel


__all__ = ["BaseModel", "BaseSingleModel"]
