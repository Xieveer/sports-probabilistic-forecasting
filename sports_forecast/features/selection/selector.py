"""FeatureSelector — оркестратор отбора фичей.

Комбинирует результаты нескольких ранкеров (model importance,
mutual info, SHAP, permutation importance) для надёжного отбора.

Стратегии агрегации:
    - ``union``: объединение отобранных фичей (наиболее полный набор).
    - ``intersection``: пересечение (только фичи, отобранные всеми методами).
    - ``vote``: фичи, отобранные >= ``min_votes`` методами.
    - ``rank_average``: усреднение рангов (ранг = позиция в ранжировании).

Результат сохраняется в MLflow и может использоваться для фильтрации
фичей при следующем запуске обучения.

Примеры::

    selector = FeatureSelector(
        methods=["model_importance", "mutual_info"],
        strategy="vote",
        min_votes=2,
    )
    result = selector.select(X_train, y_train, model=trained_model)
    X_selected = X_train[result.selected_features]
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.features.selection.base import (
    BaseFeatureRanker,
    FeatureRankingResult,
)
from sports_forecast.utils.log_config import get_logger


if TYPE_CHECKING:
    from sports_forecast.training.base import BaseModel

logger = get_logger(__name__)


@dataclass
class FeatureSelectionResult:
    """Итоговый результат отбора фичей.

    Attributes:
        selected_features: Финальный список отобранных фичей.
        rankings: Результаты каждого метода.
        aggregated_ranking: Агрегированное ранжирование (все методы).
        strategy: Стратегия агрегации.
        metadata: Дополнительная информация.
    """

    selected_features: list[str]
    rankings: dict[str, FeatureRankingResult]
    aggregated_ranking: pd.DataFrame
    strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def n_selected(self) -> int:
        """Количество отобранных фичей."""
        return len(self.selected_features)

    @property
    def n_total(self) -> int:
        """Общее количество фичей."""
        return len(self.aggregated_ranking)

    @property
    def reduction_pct(self) -> float:
        """Процент сокращения фичей."""
        if self.n_total == 0:
            return 0.0
        return round((1.0 - self.n_selected / self.n_total) * 100, 1)

    def save_selected(self, path: Path) -> None:
        """Сохранить список отобранных фичей в текстовый файл.

        Args:
            path: Путь для сохранения.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.selected_features), encoding="utf-8")
        logger.info("Отобранные фичи сохранены: %s (%d шт.)", path, self.n_selected)

    def save_ranking(self, path: Path) -> None:
        """Сохранить агрегированное ранжирование в CSV.

        Args:
            path: Путь для сохранения.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.aggregated_ranking.to_csv(path, index=False)
        logger.info("Ранжирование сохранено: %s", path)


# ─────────────────────────────────────────────────────────────────────
# Ranker factory
# ─────────────────────────────────────────────────────────────────────

_RANKER_METHODS = {
    "model_importance",
    "permutation_importance",
    "mutual_info",
    "shap",
}


def _create_ranker(
    method: str,
    model: BaseModel | None,
    cfg: DictConfig | None,
) -> BaseFeatureRanker:
    """Фабрика ранкеров.

    Args:
        method: Имя метода.
        model: Обученная модель (нужна для model/perm/shap).
        cfg: Конфигурация feature_selection.

    Returns:
        Экземпляр BaseFeatureRanker.

    Raises:
        ValueError: Неизвестный метод.
    """
    # Lazy imports для избежания circular dependency
    # (selector → rankers → training.base → training/__init__ → trainer → selector)
    from sports_forecast.features.selection.importance_ranker import (
        ModelImportanceRanker,
        PermutationImportanceRanker,
    )
    from sports_forecast.features.selection.mutual_info_ranker import MutualInfoRanker
    from sports_forecast.features.selection.shap_ranker import ShapRanker

    top_k = int(cfg.get("top_k", 0)) if cfg else None
    if top_k == 0:
        top_k = None
    min_score_pct = float(cfg.get("min_score_pct", 0.01)) if cfg else 0.01

    if method == "model_importance":
        if model is None:
            raise ValueError("model_importance требует обученную модель")
        return ModelImportanceRanker(model=model, top_k=top_k, min_score_pct=min_score_pct)

    if method == "permutation_importance":
        if model is None:
            raise ValueError("permutation_importance требует обученную модель")
        n_repeats = int(cfg.get("perm_n_repeats", 5)) if cfg else 5
        return PermutationImportanceRanker(
            model=model,
            n_repeats=n_repeats,
            top_k=top_k,
            min_score_pct=min_score_pct,
        )

    if method == "mutual_info":
        n_neighbors = int(cfg.get("mi_n_neighbors", 5)) if cfg else 5
        return MutualInfoRanker(
            n_neighbors=n_neighbors,
            top_k=top_k,
            min_score_pct=min_score_pct,
        )

    if method == "shap":
        if model is None:
            raise ValueError("shap требует обученную модель")
        max_samples = int(cfg.get("shap_max_samples", 1000)) if cfg else 1000
        return ShapRanker(
            model=model,
            max_samples=max_samples,
            top_k=top_k,
            min_score_pct=min_score_pct,
        )

    raise ValueError(f"Неизвестный метод: '{method}'. Доступные: {_RANKER_METHODS}")


# ─────────────────────────────────────────────────────────────────────
# Aggregation strategies
# ─────────────────────────────────────────────────────────────────────


def _aggregate_union(results: dict[str, FeatureRankingResult]) -> list[str]:
    """Объединение отобранных фичей из всех методов."""
    selected: set[str] = set()
    for r in results.values():
        selected.update(r.selected)
    return sorted(selected)


def _aggregate_intersection(results: dict[str, FeatureRankingResult]) -> list[str]:
    """Пересечение отобранных фичей: только фичи, одобренные всеми."""
    sets = [set(r.selected) for r in results.values()]
    if not sets:
        return []
    common = sets[0]
    for s in sets[1:]:
        common &= s
    return sorted(common)


def _aggregate_vote(
    results: dict[str, FeatureRankingResult],
    min_votes: int,
) -> list[str]:
    """Голосование: фичи, отобранные >= min_votes методами."""
    vote_count: dict[str, int] = {}
    for r in results.values():
        for f in r.selected:
            vote_count[f] = vote_count.get(f, 0) + 1

    return sorted(f for f, cnt in vote_count.items() if cnt >= min_votes)


def _aggregate_rank_average(
    results: dict[str, FeatureRankingResult],
    top_k: int | None = None,
) -> tuple[list[str], pd.DataFrame]:
    """Усреднение рангов: feature → средний ранг по всем методам.

    Returns:
        Tuple (selected_features, aggregated_df).
    """
    rank_dfs: list[pd.DataFrame] = []

    for method, r in results.items():
        df = r.ranking.copy()
        df["rank"] = range(1, len(df) + 1)
        df = df.rename(columns={"score": f"score_{method}", "rank": f"rank_{method}"})
        rank_dfs.append(df[["feature", f"score_{method}", f"rank_{method}"]])

    if not rank_dfs:
        return [], pd.DataFrame()

    merged = rank_dfs[0]
    for df in rank_dfs[1:]:
        merged = merged.merge(df, on="feature", how="outer")

    # Средний ранг (заполняем пропуски максимальным рангом)
    rank_cols = [c for c in merged.columns if c.startswith("rank_")]
    max_rank = len(merged)
    merged[rank_cols] = merged[rank_cols].fillna(max_rank)
    merged["avg_rank"] = merged[rank_cols].mean(axis=1)

    # Score = 1 / avg_rank (нормализованный)
    score_cols = [c for c in merged.columns if c.startswith("score_")]
    merged[score_cols] = merged[score_cols].fillna(0.0)
    merged["avg_score"] = merged[score_cols].mean(axis=1)

    merged = merged.sort_values("avg_rank").reset_index(drop=True)

    selected = list(merged["feature"].head(top_k)) if top_k is not None else list(merged["feature"])

    return selected, merged


# ─────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────


class FeatureSelector:
    """Оркестратор отбора фичей.

    Запускает несколько ранкеров и агрегирует результаты.

    Args:
        methods: Список методов ранжирования.
        strategy: Стратегия агрегации
            (``"union"``, ``"intersection"``, ``"vote"``, ``"rank_average"``).
        min_votes: Минимальное количество голосов для strategy="vote".
        config: Hydra конфигурация ``feature_selection``.

    Examples:
        >>> selector = FeatureSelector(
        ...     methods=["model_importance", "mutual_info"],
        ...     strategy="vote",
        ...     min_votes=2,
        ... )
        >>> result = selector.select(X_train, y_train, model=model)
        >>> X_filtered = X_train[result.selected_features]
    """

    STRATEGIES = {"union", "intersection", "vote", "rank_average"}

    def __init__(
        self,
        methods: list[str] | None = None,
        strategy: str = "vote",
        min_votes: int = 2,
        config: DictConfig | None = None,
    ) -> None:
        self.methods = methods or ["model_importance", "mutual_info"]
        self.strategy = strategy
        self.min_votes = min_votes
        self.config = config

        if strategy not in self.STRATEGIES:
            raise ValueError(f"Неизвестная стратегия: '{strategy}'. Доступные: {self.STRATEGIES}")

        for m in self.methods:
            if m not in _RANKER_METHODS:
                raise ValueError(f"Неизвестный метод: '{m}'. Доступные: {_RANKER_METHODS}")

    def select(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model: BaseModel | None = None,
    ) -> FeatureSelectionResult:
        """Запустить отбор фичей.

        Args:
            X: DataFrame с фичами.
            y: Series с таргетом.
            model: Обученная модель (нужна для model_importance, shap, permutation).

        Returns:
            FeatureSelectionResult.
        """
        t0 = time.perf_counter()

        logger.info("=" * 60)
        logger.info("FEATURE SELECTION")
        logger.info("  Методы: %s", self.methods)
        logger.info("  Стратегия: %s", self.strategy)
        logger.info("  Всего фичей: %d", X.shape[1])
        logger.info("=" * 60)

        # Запускаем каждый ранкер
        rankings: dict[str, FeatureRankingResult] = {}
        for method in self.methods:
            try:
                ranker = _create_ranker(method, model, self.config)
                result = ranker.rank(X, y)
                rankings[method] = result
                logger.info(
                    "  %s: отобрано %d / %d фичей",
                    method,
                    result.n_selected,
                    result.n_total,
                )
            except Exception as e:
                logger.warning("  %s: ошибка — %s", method, e)

        if not rankings:
            logger.warning("Ни один метод не вернул результат, сохраняем все фичи")
            return FeatureSelectionResult(
                selected_features=list(X.columns),
                rankings={},
                aggregated_ranking=pd.DataFrame({"feature": list(X.columns), "score": 1.0}),
                strategy=self.strategy,
            )

        # Агрегация
        selected, agg_df = self._aggregate(rankings, X)
        elapsed = time.perf_counter() - t0

        logger.info("-" * 60)
        logger.info(
            "Feature Selection завершён: %d → %d фичей (%.1f%% сокращение, %.2fs)",
            X.shape[1],
            len(selected),
            (1 - len(selected) / X.shape[1]) * 100 if X.shape[1] > 0 else 0,
            elapsed,
        )

        return FeatureSelectionResult(
            selected_features=selected,
            rankings=rankings,
            aggregated_ranking=agg_df,
            strategy=self.strategy,
            metadata={
                "elapsed_sec": round(elapsed, 3),
                "methods": self.methods,
                "n_features_before": X.shape[1],
                "n_features_after": len(selected),
            },
        )

    def _aggregate(
        self,
        rankings: dict[str, FeatureRankingResult],
        X: pd.DataFrame,
    ) -> tuple[list[str], pd.DataFrame]:
        """Агрегировать результаты ранкеров.

        Args:
            rankings: Результаты каждого метода.
            X: Исходный DataFrame с фичами.

        Returns:
            Tuple (selected features, aggregated DataFrame).
        """
        if self.strategy == "union":
            selected = _aggregate_union(rankings)
            agg_df = self._build_aggregated_df(rankings, X)
            return selected, agg_df

        if self.strategy == "intersection":
            selected = _aggregate_intersection(rankings)
            agg_df = self._build_aggregated_df(rankings, X)
            return selected, agg_df

        if self.strategy == "vote":
            selected = _aggregate_vote(rankings, self.min_votes)
            agg_df = self._build_aggregated_df(rankings, X)
            return selected, agg_df

        if self.strategy == "rank_average":
            top_k = int(self.config.get("top_k", 0)) if self.config else None
            if top_k == 0:
                top_k = None
            return _aggregate_rank_average(rankings, top_k=top_k)

        return list(X.columns), pd.DataFrame()

    @staticmethod
    def _build_aggregated_df(
        rankings: dict[str, FeatureRankingResult],
        X: pd.DataFrame,
    ) -> pd.DataFrame:
        """Построить агрегированную таблицу ранжирования.

        Args:
            rankings: Результаты методов.
            X: Исходный DataFrame.

        Returns:
            DataFrame с колонками: feature, score_method1, ..., avg_score.
        """
        all_features = list(X.columns)
        agg = pd.DataFrame({"feature": all_features})

        for method, r in rankings.items():
            method_df = r.ranking.rename(columns={"score": f"score_{method}"})
            agg = agg.merge(
                method_df[["feature", f"score_{method}"]],
                on="feature",
                how="left",
            )

        score_cols = [c for c in agg.columns if c.startswith("score_")]
        agg[score_cols] = agg[score_cols].fillna(0.0)
        agg["avg_score"] = agg[score_cols].mean(axis=1)

        return agg.sort_values("avg_score", ascending=False).reset_index(drop=True)

    @classmethod
    def from_config(cls, cfg: DictConfig) -> FeatureSelector:
        """Создать FeatureSelector из Hydra конфигурации.

        Args:
            cfg: Конфигурация ``feature_selection``.

        Returns:
            Экземпляр FeatureSelector.

        Examples:
            >>> selector = FeatureSelector.from_config(cfg.feature_selection)
        """
        methods = list(cfg.get("methods", ["model_importance", "mutual_info"]))
        strategy = str(cfg.get("strategy", "vote"))
        min_votes = int(cfg.get("min_votes", 2))

        return cls(
            methods=methods,
            strategy=strategy,
            min_votes=min_votes,
            config=cfg,
        )
