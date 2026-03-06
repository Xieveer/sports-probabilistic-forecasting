"""Feature Selection — модуль отбора фичей.

Поддерживаемые методы:
    - Model importance (CatBoost/LightGBM native feature_importances_)
    - Mutual Information (sklearn mutual_info_classif)
    - Permutation importance (sklearn permutation_importance)
    - SHAP values (shap.TreeExplainer)

Оркестратор ``FeatureSelector`` комбинирует результаты нескольких
методов для надёжного отбора.
"""

from sports_forecast.features.selection.selector import FeatureSelector


__all__ = ["FeatureSelector"]
