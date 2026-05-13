"""Smoke: Hydra ``nhl`` + walk_forward.enabled."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.features.selection.selector import FeatureSelectionResult
from sports_forecast.training.trainer import SingleExperimentRunner
from sports_forecast.training.walk_forward.runner import WalkForwardRunner


def _tiny_nhl_like_df() -> pd.DataFrame:
    """Long-format rows: train season vs holdout, OOS across months."""
    rows: list[dict[str, object]] = []
    base_train = pd.Timestamp("2023-10-01")
    for i in range(8):
        rows.append(
            {
                "datetime": base_train + pd.Timedelta(days=i),
                "season": 20222023,
                "f_dummy": float(i % 2),
                "f_extra": float(i % 3),
                "odds_raw": '{"winner_home": 2.0}',
                "pl": "A",
                "opp": "B",
                "side": "h",
                "is_home": 1,
                "pl_goals_full": 3,
                "opp_goals_full": 2,
                "match_id": i,
                "id": i,
                "target_is_win": 1 if i % 2 == 0 else 0,
            }
        )
    oos_dates = pd.to_datetime(["2024-02-01", "2024-02-15", "2024-03-01", "2024-04-10"])
    for j, dt in enumerate(oos_dates):
        rows.append(
            {
                "datetime": dt,
                "season": 20232024,
                "f_dummy": 0.5,
                "f_extra": 0.25,
                "odds_raw": '{"winner_home": 2.0}',
                "pl": "A",
                "opp": "B",
                "side": "h",
                "is_home": 1,
                "pl_goals_full": 2,
                "opp_goals_full": 3,
                "match_id": 100 + j,
                "id": 100 + j,
                "target_is_win": j % 2,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def wf_nhl_cfg() -> Any:
    conf_dir = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base=None, config_dir=str(conf_dir), job_name="pytest_wf"):
        return compose(
            config_name="config",
            overrides=[
                "tournament=nhl",
                "market=winner_withOT",
                "market_spec=winner_withOT",
                "algorithm=dummy",
                "features=basic",
                "walk_forward.enabled=true",
                "tournament.train_eval_split.holdout_seasons=[20232024]",
                "betting.enabled=false",
                "hyper.enabled=false",
                "feature_selection.enabled=false",
                "calibration.enabled=false",
            ],
        )


def test_walk_forward_integration_smoke(tmp_path: Path, wf_nhl_cfg: Any) -> None:
    df = _tiny_nhl_like_df()
    cfg_market = OmegaConf.to_container(wf_nhl_cfg.market_spec, resolve=True)
    assert isinstance(cfg_market, dict)
    cfg_market["target_name"] = "target_is_win"
    wf_nhl_cfg.market_spec = OmegaConf.create(cfg_market)

    runner = SingleExperimentRunner(wf_nhl_cfg, tmp_path)
    mock_ml = MagicMock()
    with (
        patch.object(runner, "_register_model_in_mlflow", MagicMock()),
        patch("sports_forecast.training.trainer.mlflow", mock_ml),
    ):
        ok = runner._train_model(df, df["target_is_win"], wf_nhl_cfg, "pytest_wf")

    assert ok
    metric_names = [c.args[0] for c in mock_ml.log_metric.call_args_list if c.args]
    assert any("wf_agg_" in str(x) for x in metric_names)
    tag_calls = {c.args[0]: c.args[1] for c in mock_ml.set_tag.call_args_list if len(c.args) >= 2}
    assert tag_calls.get("walk_forward") == "true"


def test_walk_forward_apply_selected_passes_subset_to_runner(
    tmp_path: Path,
    wf_nhl_cfg: Any,
) -> None:
    """R34 rework: при WF + apply_selected_to_fit в WalkForwardRunner уходят только отобранные колонки."""
    df = _tiny_nhl_like_df()
    cfg_market = OmegaConf.to_container(wf_nhl_cfg.market_spec, resolve=True)
    assert isinstance(cfg_market, dict)
    cfg_market["target_name"] = "target_is_win"
    wf_nhl_cfg.market_spec = OmegaConf.create(cfg_market)
    wf_nhl_cfg.feature_selection.enabled = True
    wf_nhl_cfg.feature_selection.apply_selected_to_fit = True
    wf_nhl_cfg.feature_selection.methods = ["model_importance"]

    fs_result = FeatureSelectionResult(
        selected_features=["f_dummy"],
        rankings={},
        aggregated_ranking=pd.DataFrame(
            {"feature": ["f_dummy", "f_extra"], "aggregated_score": [1.0, 0.1]}
        ),
        strategy="vote",
        metadata={"methods": ["model_importance"]},
    )

    captured: dict[str, list[str]] = {}
    orig_run = WalkForwardRunner.run

    def run_capture(self: WalkForwardRunner, *args: Any, **kwargs: Any) -> Any:
        captured["feature_names"] = list(kwargs.get("feature_names") or [])
        return orig_run(self, *args, **kwargs)

    runner = SingleExperimentRunner(wf_nhl_cfg, tmp_path)
    mock_ml = MagicMock()
    with (
        patch.object(runner, "_register_model_in_mlflow", MagicMock()),
        patch.object(runner, "_run_feature_selection", return_value=fs_result),
        patch("sports_forecast.training.trainer.WalkForwardRunner.run", run_capture),
        patch("sports_forecast.training.trainer.mlflow", mock_ml),
    ):
        ok = runner._train_model(df, df["target_is_win"], wf_nhl_cfg, "pytest_wf_fs")

    assert ok
    assert captured.get("feature_names") == ["f_dummy"]
