"""Метрики 1X2 используют три класса и порядок модели."""

from typing import cast

import numpy as np
import pandas as pd
import pytest
from hydra import compose, initialize_config_dir

from sports_forecast.training.base import BaseModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.training.probability_metrics import (
    audit_long_1x2_probabilities,
    compose_long_1x2_probabilities,
    evaluate_multiclass_probabilities,
)
from sports_forecast.training.trainer import (
    SingleExperimentRunner,
    supports_binary_training_component,
)


def test_metrics_map_permuted_classes_without_binary_projection() -> None:
    target = np.array([0, 1, 2])
    classes = np.array([2, 0, 1])
    probabilities = np.array([[0.1, 0.8, 0.1], [0.1, 0.2, 0.7], [0.7, 0.2, 0.1]])
    metrics = evaluate_multiclass_probabilities(target, probabilities, classes)
    assert metrics["accuracy"] == 1.0
    assert 0 < metrics["logloss"] < 1
    assert 0 < metrics["brier"] < 1


def test_metrics_reject_incomplete_probability_space() -> None:
    try:
        evaluate_multiclass_probabilities(
            np.array([0, 1, 2]), np.array([[0.7, 0.3]] * 3), np.array([0, 1])
        )
    except ValueError as exc:
        assert "три" in str(exc)
    else:
        raise AssertionError("Неполный 1X2 должен останавливать оценку")


def test_long_wins_produce_draw_residual_without_normalization() -> None:
    frame = pd.DataFrame({"id": ["a", "a"], "is_home": [1, 0]})
    result = compose_long_1x2_probabilities(frame, np.array([0.4, 0.3]))
    assert result.at["a", "home_win"] == pytest.approx(0.4)
    assert result.at["a", "draw"] == pytest.approx(0.3)
    assert result.at["a", "away_win"] == pytest.approx(0.3)


def test_long_wins_reject_negative_draw_residual() -> None:
    frame = pd.DataFrame({"id": ["a", "a"], "is_home": [1, 0]})
    with pytest.raises(ValueError, match="отрицательный остаток"):
        compose_long_1x2_probabilities(frame, np.array([0.7, 0.4]))


def test_long_audit_rejects_only_invalid_event() -> None:
    frame = pd.DataFrame({"id": ["a", "a", "b", "b"], "is_home": [1, 0, 1, 0]})
    valid, rejected = audit_long_1x2_probabilities(frame, np.array([0.4, 0.3, 0.7, 0.4]))
    assert valid.index.tolist() == ["a"]
    assert rejected.index.tolist() == ["b"]
    assert rejected.loc["b", "reason"] == "negative_draw_residual"
    assert len(rejected) / (len(valid) + len(rejected)) == 0.5


def test_tscv_rejects_fold_without_all_1x2_classes() -> None:
    frame = pd.DataFrame({"x": range(15)})
    target = pd.Series([0] * 5 + [1] * 5 + [2] * 5)
    with pytest.raises(ValueError, match="не содержит все классы 1X2"):
        TimeSeriesCrossValidator(n_splits=2).cross_validate(object(), frame, target)


def test_club_1x2_default_config_uses_market_betting_without_binary_components() -> None:
    from sports_forecast.config.loaders import PROJECT_ROOT

    with initialize_config_dir(version_base="1.3", config_dir=str(PROJECT_ROOT / "conf")):
        cfg = compose(
            config_name="config",
            overrides=[
                "tournament=football_top_leagues",
                "market=winner",
                "market_spec=winner_1x2",
                "algorithm=catboost",
                "features=basic",
            ],
        )
    assert cfg.calibration.enabled is True
    assert cfg.betting.enabled is True
    assert not supports_binary_training_component(cfg, "binary_calibration")
    assert not supports_binary_training_component(cfg, "binary_betting_simulator")

    class ModelStub:
        classes_ = np.array([0, 1, 2])

        def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
            assert len(features) == 3
            return np.array([[0.5, 0.3, 0.2], [0.2, 0.5, 0.3], [0.2, 0.3, 0.5]])

    events = pd.DataFrame(
        {
            "id": ["a", "b", "c"],
            "odd_home": [3.0] * 3,
            "odd_draw": [4.0] * 3,
            "odd_away": [4.0] * 3,
        }
    )
    runner = SingleExperimentRunner(cfg, PROJECT_ROOT)
    result = runner._compute_business_metrics(
        cast(BaseModel, ModelStub()),
        pd.DataFrame(index=range(3)),
        pd.Series([0, 1, 2]),
        events,
        cfg,
        save_bet_trace_file=False,
    )
    assert result["n_total_events"] == 3
    assert result["n_bets"] == 3
    assert result["valid_distribution_count"] == 3
