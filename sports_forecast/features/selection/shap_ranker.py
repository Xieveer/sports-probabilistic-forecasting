"""SHAP-based Feature Ranker.

Использует ``shap.TreeExplainer`` для tree-based моделей
и ``shap.LinearExplainer`` для линейных.

Преимущества:
    - Теоретически обоснованный (Shapley values).
    - Учитывает взаимодействия фичей.
    - Даёт направление влияния (положительное/отрицательное).

Зависимость: ``shap`` (опциональная, ставится отдельно).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from sports_forecast.features.selection.base import BaseFeatureRanker, FeatureRankingResult
from sports_forecast.utils.log_config import get_logger


if TYPE_CHECKING:
    from sports_forecast.training.base import BaseModel

logger = get_logger(__name__)


class ShapRanker(BaseFeatureRanker):
    """Ранкер фичей на основе SHAP values.

    Поддерживает:
        - CatBoost (TreeExplainer)
        - LightGBM (TreeExplainer)
        - LogReg (LinearExplainer)

    Args:
        model: Обученная модель.
        max_samples: Максимальное число сэмплов для SHAP
            (для ускорения на больших датасетах).
        top_k: Количество лучших фичей.
        min_score_pct: Минимальный % от max score.

    Examples:
        >>> ranker = ShapRanker(model, max_samples=500)
        >>> result = ranker.rank(X_test, y_test)
        >>> print(result.ranking.head(10))
    """

    def __init__(
        self,
        model: BaseModel,
        max_samples: int = 1000,
        top_k: int | None = None,
        min_score_pct: float = 0.01,
    ) -> None:
        super().__init__(top_k=top_k, min_score_pct=min_score_pct)
        self.model = model
        self.max_samples = max_samples

    def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
        """Ранжировать фичи по SHAP values.

        Args:
            X: DataFrame с фичами.
            y: Series с таргетом (не используется напрямую).

        Returns:
            FeatureRankingResult.
        """
        try:
            import shap
        except ImportError:
            logger.warning(
                "ShapRanker: shap не установлен. "
                "Установите: uv add shap. Возвращаем пустой результат."
            )
            ranking = pd.DataFrame({"feature": list(X.columns), "score": 0.0})
            return FeatureRankingResult(
                method="shap",
                ranking=ranking,
                selected=list(X.columns),
                metadata={"error": "shap not installed"},
            )

        t0 = time.perf_counter()

        # Subsample для ускорения
        X_sample = X.sample(n=self.max_samples, random_state=42) if len(X) > self.max_samples else X

        inner_model = getattr(self.model, "model_", self.model)

        # Выбираем explainer
        try:
            explainer = shap.TreeExplainer(inner_model)
            shap_values = explainer.shap_values(X_sample)

            # Для бинарной классификации: shap_values может быть list[array, array]
            if isinstance(shap_values, list):
                shap_values = shap_values[1]  # Класс 1

        except Exception:
            logger.info("TreeExplainer не подошёл, пробуем LinearExplainer")
            try:
                masker = shap.maskers.Independent(X_sample, max_samples=100)
                explainer = shap.LinearExplainer(inner_model, masker)
                shap_values = explainer.shap_values(X_sample)
            except Exception:
                logger.warning("ShapRanker: не удалось вычислить SHAP values")
                ranking = pd.DataFrame({"feature": list(X.columns), "score": 0.0})
                return FeatureRankingResult(
                    method="shap",
                    ranking=ranking,
                    selected=list(X.columns),
                    metadata={"error": "shap computation failed"},
                )

        # mean(|SHAP|) для каждой фичи
        mean_abs_shap = np.abs(shap_values).mean(axis=0)

        ranking = (
            pd.DataFrame({"feature": list(X_sample.columns), "score": mean_abs_shap})
            .sort_values("score", ascending=False)
            .reset_index(drop=True)
        )

        # Нормализуем
        max_val = ranking["score"].max()
        if max_val > 0:
            ranking["score"] = ranking["score"] / max_val

        selected = self._select_top(ranking)
        elapsed = time.perf_counter() - t0

        logger.info(
            "ShapRanker: %d / %d фичей отобрано (%.2fs, %d samples)",
            len(selected),
            len(ranking),
            elapsed,
            len(X_sample),
        )

        return FeatureRankingResult(
            method="shap",
            ranking=ranking,
            selected=selected,
            metadata={
                "elapsed_sec": round(elapsed, 3),
                "n_samples": len(X_sample),
            },
        )
