"""Тесты для build_optuna_study_suffix / build_optuna_study_name."""

from __future__ import annotations

from omegaconf import OmegaConf

from sports_forecast.training.optimization.optuna_study_name import (
    build_optuna_study_name,
    build_optuna_study_suffix,
)


def _base_cfg() -> OmegaConf:
    return OmegaConf.create(
        {
            "tournament": {
                "name": "nhl_train",
                "train_eval_split": {
                    "kind": "season_holdout",
                    "season_column": "season",
                    "holdout_seasons": ["20242025"],
                    "train_seasons": None,
                },
            },
            "features": {"name": "advanced"},
            "split": {"strategy": "time_series", "test_size": 0.1, "tscv_n_splits": 4},
            "hyper": {
                "metric": "logloss",
                "sampler": {"type": "TPESampler", "seed": 42},
            },
        }
    )


def test_suffix_stable_for_same_inputs() -> None:
    cfg = _base_cfg()
    a = build_optuna_study_suffix(cfg, 34479)
    b = build_optuna_study_suffix(cfg, 34479)
    assert a == b
    assert a.startswith("d")
    assert len(a) == 13  # d + 12 hex


def test_suffix_changes_when_holdout_changes() -> None:
    cfg = _base_cfg()
    s1 = build_optuna_study_suffix(cfg, 34479)
    cfg.tournament.train_eval_split.holdout_seasons = ["20232024", "20242025"]
    s2 = build_optuna_study_suffix(cfg, 34479)
    assert s1 != s2


def test_suffix_changes_when_inner_rows_change() -> None:
    cfg = _base_cfg()
    assert build_optuna_study_suffix(cfg, 1000) != build_optuna_study_suffix(cfg, 1001)


def test_optuna_study_tag_changes_suffix() -> None:
    cfg = _base_cfg()
    s1 = build_optuna_study_suffix(cfg, 1000)
    cfg.hyper["optuna_study_tag"] = "run_b"
    s2 = build_optuna_study_suffix(cfg, 1000)
    assert s1 != s2


def test_build_optuna_study_name_format() -> None:
    cfg = _base_cfg()
    name = build_optuna_study_name("nhl_train", "winner_withOT", "catboost_reg", cfg, 1000)
    assert name.startswith("nhl_train__winner_withOT__catboost_reg__d")
    assert len(name.split("__")) == 4
