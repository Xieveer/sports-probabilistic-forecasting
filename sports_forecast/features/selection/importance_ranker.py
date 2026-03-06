"""Model-based Feature Importance ранкер.

Использует native ``feature_importances_`` из CatBoost / LightGBM
или ``coef_`` из LogisticRegression.

Самый быстрый метод: не требует дополнительных вычислений,
поскольку importance уже вычислена при обучении модели.
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


class ModelImportanceRanker(BaseFeatureRanker):
    """Ранкер на основе встроенной важности модели.

    Поддерживает:
        - CatBoost: ``feature_importances_`` (PredictionValuesChange)
        - LightGBM: ``feature_importances_`` (split / gain)
        - LogReg: ``|coef_|``

    Args:
        model: Обученная модель (BaseSingleModel).
        top_k: Количество лучших фичей.
        min_score_pct: Минимальный % от max score.

    Examples:
        >>> model = CatBoostModel(cfg)
        >>> model.fit(X_train, y_train)
        >>> ranker = ModelImportanceRanker(model)
        >>> result = ranker.rank(X_train, y_train)
        >>> print(result.selected[:5])
    """

    def __init__(
        self,
        model: BaseModel,
        top_k: int | None = None,
        min_score_pct: float = 0.01,
    ) -> None:
        super().__init__(top_k=top_k, min_score_pct=min_score_pct)
        self.model = model

    def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
        """Ранжировать фичи по model importance.

        Args:
            X: DataFrame с фичами (нужны имена колонок).
            y: Series с таргетом (не используется, модель уже обучена).

        Returns:
            FeatureRankingResult.
        """
        t0 = time.perf_counter()

        importance_df = self.model.get_feature_importance()
        if importance_df is None or importance_df.empty:
            logger.warning(
                "ModelImportanceRanker: модель '%s' не поддерживает feature_importance",
                self.model.get_name(),
            )
            ranking = pd.DataFrame({"feature": list(X.columns), "score": 0.0})
            return FeatureRankingResult(
                method="model_importance",
                ranking=ranking,
                selected=list(X.columns),
                metadata={"error": "importance not available"},
            )

        # Нормализуем score в [0, 1]
        ranking = importance_df.rename(columns={"importance": "score"}).copy()
        max_val = ranking["score"].max()
        if max_val > 0:
            ranking["score"] = ranking["score"] / max_val

        ranking = ranking.sort_values("score", ascending=False).reset_index(drop=True)

        # Оставляем только фичи, которые есть в X
        ranking = ranking[ranking["feature"].isin(X.columns)].reset_index(drop=True)

        selected = self._select_top(ranking)
        elapsed = time.perf_counter() - t0

        logger.info(
            "ModelImportanceRanker: %d / %d фичей отобрано (%.2fs)",
            len(selected),
            len(ranking),
            elapsed,
        )

        return FeatureRankingResult(
            method="model_importance",
            ranking=ranking,
            selected=selected,
            metadata={
                "elapsed_sec": round(elapsed, 3),
                "model_name": self.model.get_name(),
            },
        )


class PermutationImportanceRanker(BaseFeatureRanker):
    """Ранкер на основе Permutation Importance.

    Перемешивает каждую фичу по очереди и измеряет падение
    метрики (neg_log_loss). Более надёжный, но медленнее.

    Args:
        model: Обученная модель.
        n_repeats: Количество перемешиваний.
        top_k: Количество лучших фичей.
        min_score_pct: Минимальный % от max score.
        random_state: Random seed.

    Examples:
        >>> ranker = PermutationImportanceRanker(model, n_repeats=5)
        >>> result = ranker.rank(X_test, y_test)
    """

    def __init__(
        self,
        model: BaseModel,
        n_repeats: int = 5,
        top_k: int | None = None,
        min_score_pct: float = 0.01,
        random_state: int = 42,
    ) -> None:
        super().__init__(top_k=top_k, min_score_pct=min_score_pct)
        self.model = model
        self.n_repeats = n_repeats
        self.random_state = random_state

    def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
        """Ранжировать фичи через Permutation Importance.

        Args:
            X: DataFrame с фичами.
            y: Series с таргетом.

        Returns:
            FeatureRankingResult.
        """
        from sklearn.inspection import permutation_importance

        t0 = time.perf_counter()

        # Получаем sklearn-совместимую модель
        inner_model = getattr(self.model, "model_", self.model)

        perm_result = permutation_importance(
            inner_model,
            X,
            y,
            n_repeats=self.n_repeats,
            scoring="neg_log_loss",
            random_state=self.random_state,
            n_jobs=-1,
        )

        importances_mean = np.abs(perm_result.importances_mean)

        ranking = (
            pd.DataFrame({"feature": list(X.columns), "score": importances_mean})
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
            "PermutationImportanceRanker: %d / %d фичей отобрано (%.2fs)",
            len(selected),
            len(ranking),
            elapsed,
        )

        return FeatureRankingResult(
            method="permutation_importance",
            ranking=ranking,
            selected=selected,
            metadata={
                "elapsed_sec": round(elapsed, 3),
                "n_repeats": self.n_repeats,
            },
        )
