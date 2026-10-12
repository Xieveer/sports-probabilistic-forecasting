"""Метрики 1X2 используют три класса и порядок модели."""

import numpy as np
import pandas as pd
import pytest
from hydra import compose, initialize_config_dir

from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.training.probability_metrics import evaluate_multiclass_probabilities
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


def test_tscv_rejects_fold_without_all_1x2_classes() -> None:
    frame = pd.DataFrame({"x": range(15)})
    target = pd.Series([0] * 5 + [1] * 5 + [2] * 5)
    with pytest.raises(ValueError, match="не содержит все классы 1X2"):
        TimeSeriesCrossValidator(n_splits=2).cross_validate(object(), frame, target)


def test_club_1x2_default_config_skips_binary_calibration_and_betting() -> None:
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
    runner = SingleExperimentRunner(cfg, PROJECT_ROOT)
    assert (
        runner._compute_business_metrics(
            None, pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame(), cfg
        )
        == {}
    )
