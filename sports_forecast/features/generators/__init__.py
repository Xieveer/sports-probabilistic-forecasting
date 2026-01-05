"""
Генераторы фичей для sports_forecast.

Доступные генераторы:
    - BaseFeatureGenerator: Абстрактный базовый класс
    - EWMFeatureGenerator: Экспоненциально взвешенные скользящие средние
    - CountFeatureGenerator: Подсчет встреч в контексте
    - FormFeatureGenerator: Форма игрока (first game, double play)
"""

from sports_forecast.features.generators.base import BaseFeatureGenerator

__all__ = ["BaseFeatureGenerator"]

