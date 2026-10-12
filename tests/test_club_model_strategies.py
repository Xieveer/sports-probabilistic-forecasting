"""Один рынок 1X2 и разные идентичности двух моделей."""

import pandas as pd
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.config.model_strategy import effective_market_spec
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
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


def test_optuna_requires_event_groups_for_1x2(tmp_path) -> None:
    cfg = _club_config("football_long_binary")
    cfg.hyper = OmegaConf.create({"enabled": True})
    runner = SingleExperimentRunner(cfg, tmp_path)
    with pytest.raises(ValueError, match="требует ID события"):
        runner._optimize_hyperparams(pd.DataFrame({"x": [1]}), pd.Series([0]), cfg)


def test_event_tscv_keeps_both_sides_in_the_same_fold() -> None:
    """Каждый ID целиком принадлежит train либо validation."""
    groups = pd.Series([event for event in range(12) for _ in range(2)])
    features = pd.DataFrame({"x": range(len(groups))})
    for train_idx, val_idx in TimeSeriesCrossValidator(n_splits=3).split(features, groups=groups):
        train_events = set(groups.iloc[train_idx])
        val_events = set(groups.iloc[val_idx])
        assert train_events.isdisjoint(val_events)
        assert all((groups.iloc[train_idx] == event).sum() == 2 for event in train_events)
        assert all((groups.iloc[val_idx] == event).sum() == 2 for event in val_events)


def test_optuna_uses_last_complete_events_before_holdout(tmp_path, monkeypatch) -> None:
    """Ограничение объёма поиска сохраняет обе стороны последних матчей."""
    import sports_forecast.training.trainer as trainer_module

    cfg = _club_config("football_long_binary")
    cfg.hyper = OmegaConf.create({"enabled": True, "max_train_events": 3})
    captured = {}

    class FakeOptimizer:
        def __init__(self, **_kwargs) -> None:
            pass

        def optimize(self, features, target, groups=None):
            captured["features"] = features
            captured["groups"] = groups
            return {"depth": 4}

        def log_to_mlflow(self, _params) -> None:
            pass

    monkeypatch.setattr(trainer_module, "OptunaHyperOptimizer", FakeOptimizer)
    groups = pd.Series([event for event in range(10) for _ in range(2)])
    features = pd.DataFrame({"x": range(20)})
    target = pd.Series([0, 1] * 10)
    runner = SingleExperimentRunner(cfg, tmp_path)
    runner._optimize_hyperparams(features, target, cfg, groups=groups)
    assert captured["groups"].tolist() == [7, 7, 8, 8, 9, 9]
    assert captured["features"]["x"].tolist() == [14, 15, 16, 17, 18, 19]


def test_club_smoke_run_does_not_claim_production_confidence(tmp_path) -> None:
    cfg = _club_config("football_wide_multiclass")
    runner = SingleExperimentRunner(cfg, tmp_path)
    metrics = runner._analyze_training_stability(
        {"logloss": 1.0, "std_logloss": 0.01}, candidate_only=True
    )
    assert metrics["prod_confidence"] == "not_assessed"
    assert metrics["std_auc"] is None
