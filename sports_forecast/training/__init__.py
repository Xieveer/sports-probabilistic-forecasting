"""
Модуль обучения моделей с поддержкой TSCV, Optuna, ансамблей и калибровки.

Основные компоненты:
    - BaseModel: Базовый класс для всех моделей
    - BaseSingleModel: Базовый класс для одиночных моделей
    - ModelFactory: Фабрика создания моделей из конфига
    - SingleExperimentRunner: Оркестратор одного эксперимента
    - TimeSeriesCrossValidator: TSCV для временных рядов
    - ModelCalibrator: Калибровка моделей
"""

from sports_forecast.training.base import BaseModel, BaseSingleModel
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.training.trainer import SingleExperimentRunner


__all__ = [
    "BaseModel",
    "BaseSingleModel",
    "ModelFactory",
    "SingleExperimentRunner",
]
