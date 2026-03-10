"""Тесты для Feature Selection Service."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from sports_forecast.features.selection.base import BaseFeatureRanker, FeatureRankingResult
from sports_forecast.features.selection.importance_ranker import ModelImportanceRanker
from sports_forecast.features.selection.mutual_info_ranker import MutualInfoRanker
from sports_forecast.features.selection.selector import (
    FeatureSelectionResult,
    FeatureSelector,
    _aggregate_intersection,
    _aggregate_rank_average,
    _aggregate_union,
    _aggregate_vote,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_data() -> tuple[pd.DataFrame, pd.Series]:
    """Генерируем тестовые данные для feature selection."""
    rng = np.random.RandomState(42)
    n = 200
    X = pd.DataFrame(
        {
            "f_useful_1": rng.randn(n) + np.arange(n) * 0.01,
            "f_useful_2": rng.randn(n) * 0.5 + np.arange(n) * 0.005,
            "f_noise_1": rng.randn(n),
            "f_noise_2": rng.randn(n),
            "f_noise_3": rng.randn(n),
        }
    )
    y = pd.Series((X["f_useful_1"] + X["f_useful_2"] > 0).astype(int))
    return X, y


@pytest.fixture
def mock_model() -> MagicMock:
    """Мок модели с feature_importance."""
    model = MagicMock()
    model.get_name.return_value = "mock_model"
    model.get_feature_importance.return_value = pd.DataFrame(
        {
            "feature": ["f_useful_1", "f_useful_2", "f_noise_1", "f_noise_2", "f_noise_3"],
            "importance": [100, 80, 5, 3, 1],
        }
    )
    return model


# ── FeatureRankingResult Tests ────────────────────────────────────────


class TestFeatureRankingResult:
    """Тесты для FeatureRankingResult dataclass."""

    def test_properties(self) -> None:
        """Проверить n_selected и n_total."""
        ranking = pd.DataFrame({"feature": ["a", "b", "c"], "score": [1.0, 0.5, 0.1]})
        result = FeatureRankingResult(
            method="test",
            ranking=ranking,
            selected=["a", "b"],
        )
        assert result.n_selected == 2
        assert result.n_total == 3
        assert result.method == "test"


# ── BaseFeatureRanker Tests ──────────────────────────────────────────


class TestBaseFeatureRanker:
    """Тесты для _select_top логики."""

    def test_select_top_by_top_k(self) -> None:
        """top_k отбирает ровно k фичей."""

        class DummyRanker(BaseFeatureRanker):
            def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
                return FeatureRankingResult(method="dummy", ranking=pd.DataFrame(), selected=[])

        ranker = DummyRanker(top_k=2)
        ranking = pd.DataFrame({"feature": ["a", "b", "c", "d"], "score": [1.0, 0.8, 0.3, 0.01]})
        selected = ranker._select_top(ranking)
        assert selected == ["a", "b"]

    def test_select_top_by_min_score_pct(self) -> None:
        """min_score_pct отсекает фичи с малым score."""

        class DummyRanker(BaseFeatureRanker):
            def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
                return FeatureRankingResult(method="dummy", ranking=pd.DataFrame(), selected=[])

        ranker = DummyRanker(min_score_pct=0.1)
        ranking = pd.DataFrame({"feature": ["a", "b", "c", "d"], "score": [1.0, 0.5, 0.05, 0.0]})
        selected = ranker._select_top(ranking)
        assert "a" in selected
        assert "b" in selected
        assert "c" not in selected  # 0.05 < 1.0 * 0.1

    def test_select_top_empty(self) -> None:
        """Пустое ранжирование — пустой результат."""

        class DummyRanker(BaseFeatureRanker):
            def rank(self, X: pd.DataFrame, y: pd.Series) -> FeatureRankingResult:
                return FeatureRankingResult(method="dummy", ranking=pd.DataFrame(), selected=[])

        ranker = DummyRanker()
        selected = ranker._select_top(pd.DataFrame({"feature": [], "score": []}))
        assert selected == []


# ── ModelImportanceRanker Tests ──────────────────────────────────────


class TestModelImportanceRanker:
    """Тесты для ModelImportanceRanker."""

    def test_rank_with_mock_model(
        self, sample_data: tuple[pd.DataFrame, pd.Series], mock_model: MagicMock
    ) -> None:
        """Ранжирование через native model importance."""
        X, y = sample_data
        ranker = ModelImportanceRanker(model=mock_model, top_k=3)
        result = ranker.rank(X, y)

        assert result.method == "model_importance"
        assert result.n_total == 5
        assert result.n_selected == 3
        assert result.selected[0] == "f_useful_1"  # Самая важная

    def test_rank_normalizes_scores(
        self, sample_data: tuple[pd.DataFrame, pd.Series], mock_model: MagicMock
    ) -> None:
        """Scores нормализованы в [0, 1]."""
        X, y = sample_data
        ranker = ModelImportanceRanker(model=mock_model)
        result = ranker.rank(X, y)

        assert result.ranking["score"].max() == pytest.approx(1.0)
        assert result.ranking["score"].min() >= 0

    def test_rank_without_importance(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """Модель без feature_importance → все фичи отобраны."""
        X, y = sample_data
        model = MagicMock()
        model.get_name.return_value = "no_importance_model"
        model.get_feature_importance.return_value = None

        ranker = ModelImportanceRanker(model=model)
        result = ranker.rank(X, y)

        assert result.n_selected == 5  # Все фичи


# ── MutualInfoRanker Tests ───────────────────────────────────────────


class TestMutualInfoRanker:
    """Тесты для MutualInfoRanker."""

    def test_rank_returns_all_features(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """MI ранкер возвращает ранжирование для всех фичей."""
        X, y = sample_data
        ranker = MutualInfoRanker(top_k=3)
        result = ranker.rank(X, y)

        assert result.method == "mutual_info"
        assert result.n_total == 5
        assert result.n_selected == 3

    def test_rank_normalizes_scores(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """MI scores нормализованы в [0, 1]."""
        X, y = sample_data
        ranker = MutualInfoRanker()
        result = ranker.rank(X, y)

        assert result.ranking["score"].max() == pytest.approx(1.0)

    def test_rank_useful_features_higher(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """Полезные фичи ранжируются выше шума."""
        X, y = sample_data
        ranker = MutualInfoRanker()
        result = ranker.rank(X, y)

        top_2 = set(result.ranking.head(2)["feature"])
        assert "f_useful_1" in top_2 or "f_useful_2" in top_2

    def test_rank_with_nan_uses_median(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """MI ранкер корректно работает с NaN (импутация медианой)."""
        X, y = sample_data
        # Вносим 20% NaN в полезную фичу
        rng = np.random.RandomState(99)
        nan_mask = rng.random(len(X)) < 0.2
        X_with_nan = X.copy()
        X_with_nan.loc[nan_mask, "f_useful_1"] = np.nan

        ranker = MutualInfoRanker()
        result = ranker.rank(X_with_nan, y)

        assert result.method == "mutual_info"
        assert result.n_total == 5
        # Полезная фича с NaN всё ещё должна быть в top-3
        # (медиана не искажает распределение, в отличие от fillna(0))
        top_3 = set(result.ranking.head(3)["feature"])
        assert "f_useful_1" in top_3

    def test_rank_with_all_nan_column(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """MI ранкер не падает при полностью NaN-колонке (fallback на 0.0)."""
        X, y = sample_data
        X_with_nan = X.copy()
        X_with_nan["f_all_nan"] = np.nan

        ranker = MutualInfoRanker()
        result = ranker.rank(X_with_nan, y)

        assert result.n_total == 6
        # all-NaN колонка должна получить низкий score
        all_nan_score = result.ranking.loc[result.ranking["feature"] == "f_all_nan", "score"].iloc[
            0
        ]
        assert all_nan_score <= 0.1  # Практически нулевой MI

    def test_no_fillna_zero_in_mi(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """Проверяем, что MI не использует fillna(0) — полезная фича с NaN > 0
        не должна получить score ниже, чем без NaN."""
        X, y = sample_data
        ranker = MutualInfoRanker(random_state=42)

        # Baseline: без NaN
        result_clean = ranker.rank(X, y)
        score_clean = result_clean.ranking.loc[
            result_clean.ranking["feature"] == "f_useful_1", "score"
        ].iloc[0]

        # С 10% NaN в f_useful_1
        X_nan = X.copy()
        rng = np.random.RandomState(42)
        nan_mask = rng.random(len(X)) < 0.1
        X_nan.loc[nan_mask, "f_useful_1"] = np.nan

        result_nan = ranker.rank(X_nan, y)
        score_nan = result_nan.ranking.loc[
            result_nan.ranking["feature"] == "f_useful_1", "score"
        ].iloc[0]

        # Score не должен деградировать сильнее чем на 50% (медиана сохраняет распределение)
        assert score_nan > score_clean * 0.5, (
            f"Score деградировал слишком сильно: {score_clean:.3f} → {score_nan:.3f}"
        )


# ── Aggregation Tests ────────────────────────────────────────────────


class TestAggregation:
    """Тесты для стратегий агрегации."""

    @pytest.fixture
    def two_rankings(self) -> dict[str, FeatureRankingResult]:
        """Два метода с разными отобранными фичами."""
        return {
            "method_a": FeatureRankingResult(
                method="method_a",
                ranking=pd.DataFrame({"feature": ["a", "b", "c"], "score": [1.0, 0.5, 0.1]}),
                selected=["a", "b"],
            ),
            "method_b": FeatureRankingResult(
                method="method_b",
                ranking=pd.DataFrame({"feature": ["a", "b", "c"], "score": [0.9, 0.8, 0.7]}),
                selected=["a", "b", "c"],
            ),
        }

    def test_union(self, two_rankings: dict[str, FeatureRankingResult]) -> None:
        """Union: объединение."""
        selected = _aggregate_union(two_rankings)
        assert set(selected) == {"a", "b", "c"}

    def test_intersection(self, two_rankings: dict[str, FeatureRankingResult]) -> None:
        """Intersection: пересечение."""
        selected = _aggregate_intersection(two_rankings)
        assert set(selected) == {"a", "b"}

    def test_vote_min_2(self, two_rankings: dict[str, FeatureRankingResult]) -> None:
        """Vote с min_votes=2: только фичи одобренные обоими."""
        selected = _aggregate_vote(two_rankings, min_votes=2)
        assert set(selected) == {"a", "b"}

    def test_vote_min_1(self, two_rankings: dict[str, FeatureRankingResult]) -> None:
        """Vote с min_votes=1: эквивалентно union."""
        selected = _aggregate_vote(two_rankings, min_votes=1)
        assert set(selected) == {"a", "b", "c"}

    def test_rank_average_missing_feature_uses_min_score(self) -> None:
        """rank_average: фича, отсутствующая в одном методе, получает min score, не 0.0."""
        rankings = {
            "method_a": FeatureRankingResult(
                method="method_a",
                ranking=pd.DataFrame(
                    {
                        "feature": ["a", "b", "c"],
                        "score": [1.0, 0.5, 0.2],
                    }
                ),
                selected=["a", "b"],
            ),
            "method_b": FeatureRankingResult(
                method="method_b",
                # "c" отсутствует в этом методе, "d" — только здесь
                ranking=pd.DataFrame(
                    {
                        "feature": ["a", "b", "d"],
                        "score": [0.9, 0.6, 0.3],
                    }
                ),
                selected=["a", "b"],
            ),
        }

        selected, agg_df = _aggregate_rank_average(rankings)

        # "c" отсутствует в method_b → score_method_b = min(method_b scores) = 0.3
        row_c = agg_df.loc[agg_df["feature"] == "c"]
        assert row_c["score_method_b"].iloc[0] == pytest.approx(0.3), (
            "Отсутствующая фича должна получить min score метода, а не 0.0"
        )

        # "d" отсутствует в method_a → score_method_a = min(method_a scores) = 0.2
        row_d = agg_df.loc[agg_df["feature"] == "d"]
        assert row_d["score_method_a"].iloc[0] == pytest.approx(0.2), (
            "Отсутствующая фича должна получить min score метода, а не 0.0"
        )

    def test_rank_average_no_nan_when_all_features_present(self) -> None:
        """rank_average: если все фичи присутствуют во всех методах, NaN нет."""
        rankings = {
            "method_a": FeatureRankingResult(
                method="method_a",
                ranking=pd.DataFrame(
                    {
                        "feature": ["a", "b"],
                        "score": [1.0, 0.5],
                    }
                ),
                selected=["a", "b"],
            ),
            "method_b": FeatureRankingResult(
                method="method_b",
                ranking=pd.DataFrame(
                    {
                        "feature": ["a", "b"],
                        "score": [0.8, 0.6],
                    }
                ),
                selected=["a", "b"],
            ),
        }

        _, agg_df = _aggregate_rank_average(rankings)

        assert not agg_df.isna().any().any(), "NaN не должно быть при полном покрытии"
        # avg_score корректный
        row_a = agg_df.loc[agg_df["feature"] == "a"]
        assert row_a["avg_score"].iloc[0] == pytest.approx((1.0 + 0.8) / 2)

    def test_build_aggregated_df_uses_min_score(self) -> None:
        """_build_aggregated_df: пропуски заполняются min score метода."""
        rankings = {
            "method_a": FeatureRankingResult(
                method="method_a",
                ranking=pd.DataFrame(
                    {
                        "feature": ["a", "b"],
                        "score": [1.0, 0.4],
                    }
                ),
                selected=["a", "b"],
            ),
        }
        X = pd.DataFrame({"a": [1], "b": [2], "c": [3]})

        agg_df = FeatureSelector._build_aggregated_df(rankings, X)

        # "c" не в method_a → score_method_a = min(1.0, 0.4) = 0.4
        row_c = agg_df.loc[agg_df["feature"] == "c"]
        assert row_c["score_method_a"].iloc[0] == pytest.approx(0.4), (
            "Пропуск заполнен min score, а не 0.0"
        )


# ── FeatureSelector Tests ────────────────────────────────────────────


class TestFeatureSelector:
    """Тесты для оркестратора FeatureSelector."""

    def test_select_with_mutual_info(self, sample_data: tuple[pd.DataFrame, pd.Series]) -> None:
        """Feature selection только с mutual_info (без модели)."""
        X, y = sample_data
        selector = FeatureSelector(
            methods=["mutual_info"],
            strategy="union",
        )
        result = selector.select(X, y)

        assert isinstance(result, FeatureSelectionResult)
        assert result.n_total == 5
        assert result.n_selected > 0
        assert result.strategy == "union"

    def test_select_with_model_importance(
        self,
        sample_data: tuple[pd.DataFrame, pd.Series],
        mock_model: MagicMock,
    ) -> None:
        """Feature selection с model_importance."""
        X, y = sample_data
        selector = FeatureSelector(
            methods=["model_importance"],
            strategy="union",
        )
        result = selector.select(X, y, model=mock_model)

        assert result.n_total == 5
        assert "model_importance" in result.rankings

    def test_select_vote_strategy(
        self,
        sample_data: tuple[pd.DataFrame, pd.Series],
        mock_model: MagicMock,
    ) -> None:
        """Vote strategy с двумя методами."""
        X, y = sample_data
        selector = FeatureSelector(
            methods=["model_importance", "mutual_info"],
            strategy="vote",
            min_votes=2,
        )
        result = selector.select(X, y, model=mock_model)

        assert result.strategy == "vote"
        assert result.n_selected > 0
        # Фичи, прошедшие оба метода — наиболее важные
        assert "f_useful_1" in result.selected_features

    def test_invalid_method_raises(self) -> None:
        """Неизвестный метод вызывает ValueError."""
        with pytest.raises(ValueError, match="Неизвестный метод"):
            FeatureSelector(methods=["nonexistent"])

    def test_invalid_strategy_raises(self) -> None:
        """Неизвестная стратегия вызывает ValueError."""
        with pytest.raises(ValueError, match="Неизвестная стратегия"):
            FeatureSelector(strategy="magic")

    def test_reduction_pct(
        self,
        sample_data: tuple[pd.DataFrame, pd.Series],
        mock_model: MagicMock,
    ) -> None:
        """Процент сокращения корректно вычисляется."""
        X, y = sample_data
        selector = FeatureSelector(
            methods=["model_importance"],
            strategy="union",
        )
        result = selector.select(X, y, model=mock_model)

        expected_pct = round((1 - result.n_selected / result.n_total) * 100, 1)
        assert result.reduction_pct == expected_pct

    def test_save_selected(
        self,
        sample_data: tuple[pd.DataFrame, pd.Series],
        tmp_path: object,
    ) -> None:
        """Сохранение отобранных фичей в файл."""
        from pathlib import Path

        X, y = sample_data
        selector = FeatureSelector(methods=["mutual_info"], strategy="union")
        result = selector.select(X, y)

        path = Path(str(tmp_path)) / "selected.txt"
        result.save_selected(path)

        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == result.n_selected

    def test_save_ranking(
        self,
        sample_data: tuple[pd.DataFrame, pd.Series],
        tmp_path: object,
    ) -> None:
        """Сохранение ранжирования в CSV."""
        from pathlib import Path

        X, y = sample_data
        selector = FeatureSelector(methods=["mutual_info"], strategy="union")
        result = selector.select(X, y)

        path = Path(str(tmp_path)) / "ranking.csv"
        result.save_ranking(path)

        assert path.exists()
        loaded = pd.read_csv(path)
        assert "feature" in loaded.columns
        assert "avg_score" in loaded.columns
