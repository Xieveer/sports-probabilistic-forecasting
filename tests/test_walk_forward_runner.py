"""Tests for :class:`WalkForwardRunner` with a mocked model factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.training.walk_forward.runner import WalkForwardRunner


def _minimal_cfg(*, betting: bool = False) -> Any:
    return OmegaConf.create(
        {
            "walk_forward": {"enabled": True, "frequency": "month", "reuse_optuna_params": True},
            "betting": {
                "enabled": betting,
                "initial_bankroll": 1000.0,
                "stake_strategy": "flat",
                "flat_stake": 1.0,
                "min_edge_threshold": 0.99,
                "kelly_fraction": 0.25,
                "max_stake_fraction": 0.1,
            },
            "bookmaker": {"name": "fonbet", "market_keys": {}, "side_keys": {}},
            "market_spec": {
                "name": "winner",
                "data_format": "long",
            },
        }
    )


def test_walk_forward_runner_three_month_steps() -> None:
    train = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-15"]),
            "f1": [0.0, 1.0],
        }
    )
    test = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-02-01", "2024-02-02", "2024-03-01", "2024-04-01"]),
            "f1": [0.1, 0.2, 0.3, 0.4],
        }
    )
    train_y = pd.Series([0, 1])
    test_y = pd.Series([1, 0, 1, 0])
    features = pd.concat([train[["f1"]], test[["f1"]]], ignore_index=True)
    target = pd.concat([train_y, test_y], ignore_index=True)
    combined = pd.concat([train, test], ignore_index=True)

    fit_lengths: list[int] = []

    def _factory(_params: dict[str, Any] | None) -> Any:
        m = MagicMock()

        def _fit_side_effect(X: Any, y: Any, **_kwargs: Any) -> Any:
            fit_lengths.append(len(X))
            return m

        m.fit.side_effect = _fit_side_effect
        m.predict_proba.side_effect = lambda X: np.column_stack(
            [np.full(len(X), 0.4), np.full(len(X), 0.6)]
        )
        return m

    cfg = _minimal_cfg(betting=False)
    runner = WalkForwardRunner(cfg, create_model=_factory)
    init_end = pd.Timestamp(train["datetime"].max())
    out = runner.run(
        combined_df=combined,
        features=features,
        target=target,
        feature_names=["f1"],
        best_params={},
        init_train_end=init_end,
        time_col="datetime",
        artifact_dir=Path("/tmp/wf_test_runner"),
    )

    assert len(out.per_step_metrics) == 3
    assert fit_lengths[-1] == len(combined)
    assert not out.cumulative_test_df.empty
    assert "logloss" in out.aggregate_ml_metrics


def test_predict_only_runner_does_not_read_test_labels_or_refit_on_holdout() -> None:
    combined = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-09-01", "2024-09-20", "2024-10-10"]),
            "label_available_at": pd.to_datetime(["2024-09-08", "2024-10-02", "2024-10-17"]),
            "train_eligible": [True, True, False],
        }
    )
    features = pd.DataFrame({"f1": [0.0, 1.0, 0.5]})
    target = pd.Series([0, 1, float("nan")])
    fit_sizes: list[int] = []

    def _factory(_params: dict[str, Any] | None) -> Any:
        model = MagicMock()
        model.fit.side_effect = lambda x, y: fit_sizes.append(len(x))
        model.predict_proba.return_value = np.array([[0.4, 0.6]])
        return model

    out = WalkForwardRunner(_minimal_cfg(), create_model=_factory).run(
        combined_df=combined,
        features=features,
        target=target,
        feature_names=["f1"],
        best_params=None,
        init_train_end=pd.Timestamp("2024-09-30"),
        time_col="datetime",
        artifact_dir=Path("/tmp/wf_predict_only"),
        label_available_at_col="label_available_at",
        train_eligible_col="train_eligible",
        prediction_only=True,
    )

    assert fit_sizes == [1]
    assert out.per_step_metrics == []
    assert out.aggregate_ml_metrics == {}
    assert out.cumulative_test_df["row_index"].tolist() == [2]
    assert "y_true" not in out.cumulative_test_df
