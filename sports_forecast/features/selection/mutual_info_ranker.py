"""Mutual Information Feature Ranker.

Использует ``sklearn.feature_selection.mutual_info_classif``
для оценки зависимости каждой фичи с таргетом.

Преимущества:
    - Не требует обученной модели (model-free).
    - Обнаруживает нелинейные зависимости.
    - Быстрый на средних датасетах.
"""

from __future__ import annotations

import time

import pandas as pd
from sklearn.feature_selection import mutual_info_classif

from sports_forecast.features.selection.base import BaseFeatureRanker, FeatureRankingResult
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class MutualInfoRanker(BaseFeatureRanker):
    """Ранкер фичей на основе Mutual Information.

    Args:
        n_neighbors: Число соседей для KNN-оценки MI (default 5).
        top_k: Количество лучших фичей.
        min_score_pct: Минимальный % от max score.
        random_state: Random seed.

    Examples:
        >>> ranker = MutualInfoRanker(top_k=30)
        >>> result = ranker.rank(X_train, y_train)
        >>> print(result.ranking.head())
    """

    def __init__(
        self,
        n_neighbors: int = 5,
        top_k: int | None = None,
        min_score_pct: float = 0.01,
        random_state: int = 42,
    ) -> None:
        super().__init__(top_k=top_k, min_score_pct=min_score_pct)
        self.n_neighbors = n_neighbors
        self.random_state = random_state

    def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
        """Ранжировать фичи по Mutual Information.

        Args:
            X: DataFrame с фичами.
            y: Series с бинарным таргетом.

        Returns:
            FeatureRankingResult.
        """
        t0 = time.perf_counter()

        # Заполняем NaN нулями для MI
        X_filled = X.fillna(0)

        mi_scores = mutual_info_classif(
            X_filled,
            y,
            n_neighbors=self.n_neighbors,
            random_state=self.random_state,
        )

        ranking = (
            pd.DataFrame({"feature": list(X.columns), "score": mi_scores})
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
            "MutualInfoRanker: %d / %d фичей отобрано (%.2fs)",
            len(selected),
            len(ranking),
            elapsed,
        )

        return FeatureRankingResult(
            method="mutual_info",
            ranking=ranking,
            selected=selected,
            metadata={
                "elapsed_sec": round(elapsed, 3),
                "n_neighbors": self.n_neighbors,
            },
        )
