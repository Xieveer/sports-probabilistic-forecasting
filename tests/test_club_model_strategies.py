"""Один рынок 1X2 и разные идентичности двух моделей."""

import pandas as pd
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.config.model_strategy import effective_market_spec
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.training.trainer import SingleExperimentRunner
from sports_forecast.training.walk_forward import WalkForwardRunner


def _club_config(strategy: str, extra_overrides: list[str] | None = None):
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
            ]
            + (extra_overrides or []),
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
        def __init__(self, **kwargs) -> None:
            self.active_study_name = kwargs["study_name"]

        def optimize(self, features, target, groups=None):
            self.active_study_name += "__without_legacy_penalties__logloss"
            captured["features"] = features
            captured["groups"] = groups
            return {"depth": 4}

        def log_to_mlflow(self, _params) -> None:
            trainer_module.mlflow.set_tag("optuna_study", self.active_study_name)

    tags = {}
    monkeypatch.setattr(
        trainer_module.mlflow, "set_tag", lambda key, value: tags.update({key: value})
    )
    monkeypatch.setattr(trainer_module.mlflow, "log_param", lambda *_args: None)
    monkeypatch.setattr(trainer_module.mlflow, "log_metric", lambda *_args: None)
    monkeypatch.setattr(trainer_module.mlflow, "log_text", lambda *_args: None)
    monkeypatch.setattr(trainer_module, "OptunaHyperOptimizer", FakeOptimizer)
    groups = pd.Series([event for event in range(10) for _ in range(2)])
    features = pd.DataFrame({"x": range(20)})
    target = pd.Series([0, 1] * 10)
    runner = SingleExperimentRunner(cfg, tmp_path)
    _, metrics = runner._optimize_hyperparams(features, target, cfg, groups=groups)
    assert metrics["study_name"].endswith("__without_legacy_penalties__logloss")
    assert captured["groups"].tolist() == [7, 7, 8, 8, 9, 9]
    assert captured["features"]["x"].tolist() == [14, 15, 16, 17, 18, 19]
    runner._log_metrics_to_mlflow(
        shadow_metrics={},
        test_metrics={},
        calibration_metrics={},
        business_metrics={},
        stability_metrics={
            "cv_logloss": 0.1,
            "std_auc": None,
            "stability_level": "stable",
            "prod_confidence": "not_assessed",
            "recommendation": "none",
        },
        optuna_metrics=metrics,
        feature_importance=None,
        feature_selection_result=None,
        cfg=cfg,
        feature_names=["x"],
    )
    assert tags["optuna_study"] == metrics["study_name"]


def test_club_smoke_run_does_not_claim_production_confidence(tmp_path) -> None:
    cfg = _club_config("football_wide_multiclass")
    runner = SingleExperimentRunner(cfg, tmp_path)
    metrics = runner._analyze_training_stability(
        {"logloss": 1.0, "std_logloss": 0.01}, candidate_only=True
    )
    assert metrics["prod_confidence"] == "not_assessed"
    assert metrics["std_auc"] is None


@pytest.mark.parametrize("algorithm", ["catboost", "catboost_reg"])
@pytest.mark.parametrize(
    ("strategy", "expected_loss", "classes"),
    [
        ("football_wide_multiclass", "MultiClass", [0, 1, 2]),
        ("football_long_binary", "Logloss", [0, 1]),
        ("standard", "Logloss", [0, 1]),
    ],
)
def test_catboost_strategy_defaults_train_with_expected_classes(
    algorithm, strategy, expected_loss, classes
) -> None:
    cfg = _club_config(strategy, [f"algorithm={algorithm}"])
    cfg.algorithm.params.iterations = 3
    OmegaConf.update(cfg, "algorithm.params.allow_writing_files", False, force_add=True)
    model = ModelFactory.create_model(cfg.algorithm)
    assert isinstance(model, CatBoostModel)
    assert model.params["loss_function"] == expected_loss
    assert model.params["eval_metric"] == expected_loss
    target = pd.Series(classes * 4)
    features = pd.DataFrame({"x": range(len(target))})
    model.fit(features, target)
    assert model.predict_proba(features).shape == (len(target), len(classes))


def test_wide_catboost_explicit_loss_and_metric_overrides() -> None:
    cfg = _club_config(
        "football_wide_multiclass",
        [
            "algorithm.params.loss_function=MultiClassOneVsAll",
            "algorithm.params.eval_metric=Accuracy",
        ],
    )
    model = ModelFactory.create_model(cfg.algorithm)
    assert isinstance(model, CatBoostModel)
    assert model.params["loss_function"] == "MultiClassOneVsAll"
    assert model.params["eval_metric"] == "Accuracy"


@pytest.mark.parametrize("strategy", ["football_long_binary", "football_wide_multiclass"])
@pytest.mark.parametrize(
    "entrypoint", ["run_experiment", "run_experiment_with_dataframe", "_train_model"]
)
def test_1x2_walk_forward_rejected_before_training_or_mlflow(
    tmp_path, monkeypatch, strategy, entrypoint
) -> None:
    cfg = _club_config(strategy, ["walk_forward.enabled=true"])
    runner = SingleExperimentRunner(cfg, tmp_path)
    monkeypatch.setattr(
        "sports_forecast.training.trainer.mlflow.start_run",
        lambda **kwargs: pytest.fail("MLflow не должен запускаться"),
    )
    with pytest.raises(ValueError, match="walk_forward.*winner_1x2"):
        if entrypoint == "run_experiment":
            runner.run_experiment()
        elif entrypoint == "run_experiment_with_dataframe":
            runner.run_experiment_with_dataframe(pd.DataFrame())
        else:
            runner._train_model(pd.DataFrame(), pd.Series(dtype=int), cfg, "test")


def test_walk_forward_runner_rejects_1x2_before_model_creation(tmp_path) -> None:
    cfg = _club_config("football_long_binary", ["walk_forward.enabled=true"])
    runner = WalkForwardRunner(cfg, lambda _: pytest.fail("Модель не должна создаваться"))
    with pytest.raises(ValueError, match="walk_forward.*winner_1x2"):
        runner.run(
            combined_df=pd.DataFrame(),
            features=pd.DataFrame(),
            target=pd.Series(dtype=int),
            feature_names=[],
            best_params=None,
            init_train_end=pd.Timestamp("2025-01-01"),
            time_col="datetime",
            artifact_dir=tmp_path,
        )
