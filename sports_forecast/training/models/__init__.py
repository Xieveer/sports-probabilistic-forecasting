"""Одиночные модели для классификации."""

from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel


__all__ = [
    "CatBoostModel",
    "DummyModel",
    "LGBMModel",
    "LogRegModel",
]
