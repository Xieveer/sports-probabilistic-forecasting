"""R29: композиция generators по спорту и tournament overrides (NHL pre-gen, streak)."""

from __future__ import annotations

from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.features.rolling_contexts import materialize_features_config


def _compose_train_cfg(overrides: list[str]):
    conf_dir = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base=None, config_dir=str(conf_dir), job_name="pytest_r29"):
        return compose(config_name="config", overrides=overrides)


def test_advanced_uel_kz_1_has_no_nhl_or_streak_generators() -> None:
    cfg = _compose_train_cfg(
        [
            "tournament=uel_kz_1",
            "market=winner",
            "market_spec=winner",
            "algorithm=dummy",
            "features=advanced",
        ]
    )
    fd = materialize_features_config(cfg.features, tournament_cfg=cfg.tournament)
    keys = set(fd["generators"])
    for k in ("nhl_schedule", "nhl_standings", "nhl_roster", "streak"):
        assert k not in keys, f"unexpected generator {k} for cyberhockey + advanced"


def test_advanced_lp_ru_has_no_nhl_or_streak_generators() -> None:
    cfg = _compose_train_cfg(
        [
            "tournament=lp_ru",
            "market=winner",
            "market_spec=winner",
            "algorithm=dummy",
            "features=advanced",
        ]
    )
    fd = materialize_features_config(cfg.features, tournament_cfg=cfg.tournament)
    keys = set(fd["generators"])
    for k in ("nhl_schedule", "nhl_standings", "nhl_roster", "streak"):
        assert k not in keys


def test_advanced_nhl_has_nhl_pre_gens_and_streak() -> None:
    cfg = _compose_train_cfg(
        [
            "tournament=nhl",
            "market=winner_withOT",
            "market_spec=winner_withOT",
            "algorithm=dummy",
            "features=advanced",
        ]
    )
    fd = materialize_features_config(cfg.features, tournament_cfg=cfg.tournament)
    keys = fd["generators"]
    assert "nhl_schedule" in keys
    assert "nhl_standings" in keys
    assert "nhl_roster" in keys
    assert "streak" in keys


def test_cyberhockey_streak_opt_in_via_tournament_override() -> None:
    cfg = _compose_train_cfg(
        [
            "tournament=uel_kz_1",
            "market=winner",
            "market_spec=winner",
            "algorithm=dummy",
            "features=advanced",
        ]
    )
    t_dict = OmegaConf.to_container(cfg.tournament, resolve=True)
    assert isinstance(t_dict, dict)
    t_dict = dict(t_dict)
    t_dict["feature_pipeline_overrides"] = {"groups": {"streak": True}}
    fd = materialize_features_config(cfg.features, tournament_cfg=t_dict)
    assert "streak" in fd["generators"]
    assert "nhl_schedule" not in fd["generators"]
