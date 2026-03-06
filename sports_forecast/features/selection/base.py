"""Базовый протокол и dataclass для Feature Selection.

Все методы отбора фичей реализуют ``BaseFeatureRanker``,
который возвращает ``FeatureRankingResult``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class FeatureRankingResult:
    """Результат ранжирования фичей одним методом.

    Attributes:
        method: Имя метода (e.g. ``"shap"``, ``"mutual_info"``).
        ranking: DataFrame с колонками ``['feature', 'score']``,
            отсортированный по убыванию ``score``.
        selected: Список отобранных фичей (после порога / top-k).
        metadata: Дополнительная информация (время выполнения и т.д.).
    """

    method: str
    ranking: pd.DataFrame
    selected: list[str]
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def n_selected(self) -> int:
        """Количество отобранных фичей."""
        return len(self.selected)

    @property
    def n_total(self) -> int:
        """Общее количество фичей."""
        return len(self.ranking)


class BaseFeatureRanker(ABC):
    """Абстрактный базовый класс для методов ранжирования фичей.

    Каждый ранкер:
        1. Принимает ``X`` (фичи) и ``y`` (таргет).
        2. Вычисляет score для каждой фичи.
        3. Возвращает ``FeatureRankingResult``.

    Args:
        top_k: Количество лучших фичей для отбора.
            Если ``None`` — используется ``min_score_pct``.
        min_score_pct: Минимальный процент от максимального score.
            Фичи со score ниже ``max_score * min_score_pct`` отсекаются.
            По умолчанию ``0.01`` (1%).
    """

    def __init__(
        self,
        top_k: int | None = None,
        min_score_pct: float = 0.01,
    ) -> None:
        self.top_k = top_k
        self.min_score_pct = min_score_pct

    @abstractmethod
    def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
        """Ранжировать фичи по важности.

        Args:
            X: DataFrame с фичами.
            y: Series с таргетом (бинарный).

        Returns:
            ``FeatureRankingResult`` с ранжированием и отобранными фичами.
        """

    def _select_top(self, ranking: pd.DataFrame) -> list[str]:
        """Отобрать фичи по top_k или min_score_pct.

        Args:
            ranking: DataFrame ``['feature', 'score']``,
                отсортированный по убыванию.

        Returns:
            Список отобранных feature names.
        """
        if ranking.empty:
            return []

        if self.top_k is not None:
            return list(ranking["feature"].head(self.top_k))

        max_score = ranking["score"].max()
        if max_score <= 0:
            return list(ranking["feature"])

        threshold = max_score * self.min_score_pct
        mask = ranking["score"] >= threshold
        return list(ranking.loc[mask, "feature"])
