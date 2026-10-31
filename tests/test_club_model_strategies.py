"""Один рынок 1X2 и разные идентичности двух моделей."""

import pandas as pd
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.config.model_strategy import effective_market_spec
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.training.models.catboost import CatBoostModel
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
