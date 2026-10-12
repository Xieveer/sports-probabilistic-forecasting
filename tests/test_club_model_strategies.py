"""Один рынок 1X2 и разные идентичности двух моделей."""

import pandas as pd
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.config.model_strategy import effective_market_spec
from sports_forecast.training.trainer import SingleExperimentRunner


def _club_config(strategy: str):
    with initialize_config_dir(version_base="1.3", config_dir=str(PROJECT_ROOT / "conf")):
        return compose(
            config_name="config",
            overrides=[
                "tournament=football_top_leagues",
                "market=winner",
                "market_spec=winner_1x2",
                "algorithm=catboost",
                "features=basic",
                f"model_strategy={strategy}",
            ],
        )


def test_long_and_wide_share_market_but_not_model_identity(tmp_path) -> None:
    long_cfg = _club_config("football_long_binary")
    wide_cfg = _club_config("football_wide_multiclass")
    long_spec = effective_market_spec(long_cfg)
    wide_spec = effective_market_spec(wide_cfg)
    assert long_spec.name == wide_spec.name == "winner_1x2"
    assert (long_spec.data_format, long_spec.target_source_key) == ("long", "player_win")
    assert (wide_spec.data_format, wide_spec.target_source_key) == ("wide", "home_result_1x2")
    long_path = SingleExperimentRunner(long_cfg, tmp_path)._get_model_path(long_cfg, "shadow")
    wide_path = SingleExperimentRunner(wide_cfg, tmp_path)._get_model_path(wide_cfg, "shadow")
    assert long_path != wide_path
    assert long_path.name == "football_long_binary"
    assert wide_path.name == "football_wide_multiclass"


def test_optuna_cannot_split_long_sides_until_event_folds_exist(tmp_path) -> None:
    cfg = _club_config("football_long_binary")
    cfg.hyper = OmegaConf.create({"enabled": True})
    runner = SingleExperimentRunner(cfg, tmp_path)
    with pytest.raises(ValueError, match="event-level folds"):
        runner._optimize_hyperparams(pd.DataFrame({"x": [1]}), pd.Series([0]), cfg)


def test_club_smoke_run_does_not_claim_production_confidence(tmp_path) -> None:
    cfg = _club_config("football_wide_multiclass")
    runner = SingleExperimentRunner(cfg, tmp_path)
    metrics = runner._analyze_training_stability(
        {"logloss": 1.0, "std_logloss": 0.01}, candidate_only=True
    )
    assert metrics["prod_confidence"] == "not_assessed"
    assert metrics["std_auc"] is None
