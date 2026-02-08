"""
Deploy module — логика выбора моделей для продакшена.

Содержит:
    - ``ModelPromoter`` — выбор лучшей модели на основе метрик MLflow.
"""

from sports_forecast.deploy.promoter import ModelPromoter


__all__ = ["ModelPromoter"]
