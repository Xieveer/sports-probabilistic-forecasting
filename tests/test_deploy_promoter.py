"""
Тесты для sports_forecast/deploy/promoter.py — выбор модели для продакшена.

Покрывает:
    - CandidateModel dataclass
    - ModelPromoter: get_candidates, get_best_candidate, compare, promote
    - Фильтрация и ранжирование
    - Генерация deploy.yaml
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from sports_forecast.deploy.promoter import CandidateModel, ModelPromoter


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_run(
    run_id: str,
    run_name: str,
    algorithm: str = "catboost",
    featureset: str = "basic",
    test_logloss: float = 0.5,
    test_auc: float = 0.7,
    test_brier: float = 0.2,
    test_ece: float = 0.05,
    betting_roi: float | None = None,
    betting_n_bets: float = 0,
    tags_extra: dict | None = None,
) -> MagicMock:
    """Создать mock MLflow Run."""
    run = MagicMock()
    run.info.run_id = run_id
    run.info.artifact_uri = f"file:///mlruns/0/{run_id}/artifacts"

    tags = {
        "mlflow.runName": run_name,
        "algorithm": algorithm,
        "featureset": featureset,
        "test_validated": "true",
    }
    if tags_extra:
        tags.update(tags_extra)

    metrics: dict[str, float] = {
        "test_logloss": test_logloss,
        "test_auc": test_auc,
        "test_brier": test_brier,
        "test_ece": test_ece,
        "betting_n_bets": betting_n_bets,
    }
    if betting_roi is not None:
        metrics["betting_roi"] = betting_roi

    run.data.tags = tags
    run.data.metrics = metrics
    return run


# ─────────────────────────────────────────────────────────────────────────────
# CandidateModel
# ─────────────────────────────────────────────────────────────────────────────


class TestCandidateModel:
    """Тесты для CandidateModel dataclass."""

    def test_creation(self) -> None:
        """Создание кандидата с минимальными полями."""
        c = CandidateModel(
            run_id="abc123",
            run_name="cb__bas__s42",
            algorithm="catboost",
            featureset="basic",
            primary_metric=0.5,
        )
        assert c.run_id == "abc123"
        assert c.primary_metric == 0.5
        assert c.metrics == {}
        assert c.tags == {}

    def test_with_metrics(self) -> None:
        """Кандидат с метриками."""
        c = CandidateModel(
            run_id="abc123",
            run_name="cb__bas__s42",
            algorithm="catboost",
            featureset="basic",
            primary_metric=0.5,
            metrics={"test_auc": 0.75, "test_logloss": 0.5},
        )
        assert c.metrics["test_auc"] == 0.75


# ─────────────────────────────────────────────────────────────────────────────
# ModelPromoter._filter_and_rank
# ─────────────────────────────────────────────────────────────────────────────


class TestFilterAndRank:
    """Тесты для внутренней логики фильтрации и ранжирования."""

    def test_minimize_sorts_ascending(self) -> None:
        """Minimize → лучший run имеет наименьшую метрику."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            direction="minimize",
        )
        runs = [
            _make_run("a", "run_a", test_logloss=0.8),
            _make_run("b", "run_b", test_logloss=0.3),
            _make_run("c", "run_c", test_logloss=0.5),
        ]
        result = promoter._filter_and_rank(runs, top_n=3)
        assert result[0].run_id == "b"
        assert result[0].primary_metric == 0.3

    def test_maximize_sorts_descending(self) -> None:
        """Maximize → лучший run имеет наибольшую метрику."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_auc",
            direction="maximize",
        )
        runs = [
            _make_run("a", "run_a", test_auc=0.7),
            _make_run("b", "run_b", test_auc=0.9),
            _make_run("c", "run_c", test_auc=0.8),
        ]
        result = promoter._filter_and_rank(runs, top_n=3)
        assert result[0].run_id == "b"
        assert result[0].primary_metric == 0.9

    def test_top_n_limits_results(self) -> None:
        """top_n ограничивает количество результатов."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            direction="minimize",
        )
        runs = [
            _make_run("a", "run_a", test_logloss=0.3),
            _make_run("b", "run_b", test_logloss=0.5),
            _make_run("c", "run_c", test_logloss=0.8),
        ]
        result = promoter._filter_and_rank(runs, top_n=2)
        assert len(result) == 2

    def test_filters_by_required_tags(self) -> None:
        """Фильтрует runs без required_tags."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            direction="minimize",
            required_tags={"test_validated": "true"},
        )
        runs = [
            _make_run("a", "run_a", test_logloss=0.3),
            _make_run(
                "b",
                "run_b",
                test_logloss=0.1,
                tags_extra={"test_validated": "false"},
            ),
        ]
        result = promoter._filter_and_rank(runs, top_n=10)
        assert len(result) == 1
        assert result[0].run_id == "a"

    def test_filters_by_min_bets(self) -> None:
        """Фильтрует runs с недостаточным количеством ставок."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            direction="minimize",
            min_bets=10,
        )
        runs = [
            _make_run("a", "run_a", test_logloss=0.3, betting_n_bets=5),
            _make_run("b", "run_b", test_logloss=0.5, betting_n_bets=15),
        ]
        result = promoter._filter_and_rank(runs, top_n=10)
        assert len(result) == 1
        assert result[0].run_id == "b"

    def test_skips_runs_without_metric(self) -> None:
        """Пропускает runs без указанной метрики."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="nonexistent_metric",
            direction="minimize",
        )
        runs = [_make_run("a", "run_a")]
        result = promoter._filter_and_rank(runs, top_n=10)
        assert len(result) == 0

    def test_empty_runs(self) -> None:
        """Пустой список runs → пустой результат."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            direction="minimize",
        )
        result = promoter._filter_and_rank([], top_n=10)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# ModelPromoter.get_candidates / get_best_candidate
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCandidates:
    """Тесты для get_candidates и get_best_candidate."""

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_raises_if_experiment_not_found(self, mock_mlflow: MagicMock) -> None:
        """ValueError если MLflow эксперимент не найден."""
        mock_mlflow.get_experiment_by_name.return_value = None

        promoter = ModelPromoter(
            experiment_name="nonexistent",
            metric="test_logloss",
        )
        with pytest.raises(ValueError, match="не найден"):
            promoter.get_candidates()

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_returns_empty_if_no_runs(self, mock_mlflow: MagicMock) -> None:
        """Пустой список если нет завершённых runs."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment
        mock_mlflow.search_runs.return_value = []

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
        )
        result = promoter.get_candidates()
        assert result == []

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_returns_ranked_candidates(self, mock_mlflow: MagicMock) -> None:
        """Возвращает кандидатов отсортированных по метрике."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment

        runs = [
            _make_run("a", "cb__bas__s42", test_logloss=0.8),
            _make_run("b", "lgbm__adv__s42", test_logloss=0.3),
        ]
        mock_mlflow.search_runs.return_value = runs

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
            direction="minimize",
        )
        result = promoter.get_candidates(top_n=5)
        assert len(result) == 2
        assert result[0].primary_metric == 0.3

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_get_best_candidate(self, mock_mlflow: MagicMock) -> None:
        """get_best_candidate возвращает лучший."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment

        runs = [
            _make_run("a", "cb__bas__s42", test_logloss=0.8),
            _make_run("b", "lgbm__adv__s42", test_logloss=0.3),
        ]
        mock_mlflow.search_runs.return_value = runs

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
            direction="minimize",
        )
        best = promoter.get_best_candidate()
        assert best is not None
        assert best.run_id == "b"

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_get_best_returns_none_if_no_candidates(self, mock_mlflow: MagicMock) -> None:
        """get_best_candidate возвращает None если нет кандидатов."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment
        mock_mlflow.search_runs.return_value = []

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
        )
        assert promoter.get_best_candidate() is None


# ─────────────────────────────────────────────────────────────────────────────
# ModelPromoter.compare
# ─────────────────────────────────────────────────────────────────────────────


class TestCompare:
    """Тесты для compare (сравнительная таблица)."""

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_compare_returns_table(self, mock_mlflow: MagicMock) -> None:
        """compare выводит форматированную таблицу."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment

        runs = [
            _make_run("a", "cb__bas__s42", test_logloss=0.5, test_auc=0.7),
            _make_run("b", "lgbm__adv__s42", test_logloss=0.3, test_auc=0.85),
        ]
        mock_mlflow.search_runs.return_value = runs

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
            direction="minimize",
        )
        table = promoter.compare(top_n=5)
        assert "lgbm__adv__s42" in table
        assert "cb__bas__s42" in table
        assert "test_logloss" in table

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_compare_no_candidates(self, mock_mlflow: MagicMock) -> None:
        """compare при отсутствии кандидатов."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment
        mock_mlflow.search_runs.return_value = []

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
        )
        result = promoter.compare()
        assert "Нет подходящих" in result

    @patch("sports_forecast.deploy.promoter.mlflow")
    def test_compare_with_business_metrics(self, mock_mlflow: MagicMock) -> None:
        """compare включает бизнес-метрики если есть."""
        experiment = MagicMock()
        experiment.experiment_id = "1"
        mock_mlflow.get_experiment_by_name.return_value = experiment

        runs = [
            _make_run(
                "a",
                "cb__bas__s42",
                test_logloss=0.5,
                betting_roi=5.0,
                betting_n_bets=50,
            ),
        ]
        mock_mlflow.search_runs.return_value = runs

        promoter = ModelPromoter(
            experiment_name="test_exp",
            metric="test_logloss",
            direction="minimize",
        )
        table = promoter.compare(top_n=5)
        assert "ROI" in table


# ─────────────────────────────────────────────────────────────────────────────
# ModelPromoter.promote
# ─────────────────────────────────────────────────────────────────────────────


class TestPromote:
    """Тесты для promote."""

    def test_generates_deploy_yaml(self, tmp_path: Path) -> None:
        """Promote генерирует deploy.yaml."""
        candidate = CandidateModel(
            run_id="abc123",
            run_name="cb__bas__s42",
            algorithm="catboost",
            featureset="basic",
            primary_metric=0.35,
            metrics={
                "test_logloss": 0.35,
                "test_auc": 0.82,
                "test_brier": 0.18,
                "test_ece": 0.04,
                "test_accuracy": 0.75,
                "betting_roi": 8.5,
                "betting_profit_units": 85.0,
                "betting_n_bets": 50,
                "betting_sharpe_like": 1.2,
            },
            tags={
                "stability_level": "high",
                "prod_confidence": "high",
            },
        )

        promoter = ModelPromoter(
            experiment_name="uel_kz_1__total__over_6.5",
            metric="test_logloss",
            direction="minimize",
        )

        target_dir = tmp_path / "deploy"

        with patch("sports_forecast.deploy.promoter.mlflow"):
            promoter.promote(candidate, target_dir, generate_deploy_config=True)

        deploy_path = target_dir / "deploy.yaml"
        assert deploy_path.exists()

        config = yaml.safe_load(deploy_path.read_text())
        assert config["model"]["run_id"] == "abc123"
        assert config["model"]["algorithm"] == "catboost"
        assert config["selection"]["metric"] == "test_logloss"
        assert config["selection"]["value"] == 0.35
        assert config["metrics"]["test_auc"] == 0.82
        assert config["business"]["betting_roi"] == 8.5
        assert config["stability"]["level"] == "high"

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        """Promote создаёт target_dir если не существует."""
        candidate = CandidateModel(
            run_id="abc",
            run_name="test",
            algorithm="dummy",
            featureset="basic",
            primary_metric=0.5,
        )

        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
        )

        target_dir = tmp_path / "deep" / "nested" / "deploy"

        with patch("sports_forecast.deploy.promoter.mlflow"):
            promoter.promote(candidate, target_dir)

        assert target_dir.exists()


# ─────────────────────────────────────────────────────────────────────────────
# _check_tags
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckTags:
    """Тесты для _check_tags."""

    def test_all_tags_match(self) -> None:
        """Все required_tags совпадают → True."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            required_tags={"test_validated": "true", "algorithm": "catboost"},
        )
        tags = {"test_validated": "true", "algorithm": "catboost", "extra": "x"}
        assert promoter._check_tags(tags) is True

    def test_missing_tag(self) -> None:
        """Отсутствует required_tag → False."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            required_tags={"test_validated": "true"},
        )
        assert promoter._check_tags({}) is False

    def test_wrong_tag_value(self) -> None:
        """Неверное значение required_tag → False."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            required_tags={"test_validated": "true"},
        )
        assert promoter._check_tags({"test_validated": "false"}) is False

    def test_empty_required_tags(self) -> None:
        """Пустые required_tags → всегда True."""
        promoter = ModelPromoter(
            experiment_name="test",
            metric="test_logloss",
            required_tags={},
        )
        assert promoter._check_tags({}) is True
