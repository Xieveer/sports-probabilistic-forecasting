"""Tests for tournament-driven train/eval splits (season holdout)."""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.training.train_eval_split import (
    TrainEvalSplitError,
    normalize_season_token,
    subset_frame_for_season_holdout,
    uses_season_holdout_split,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (20242025, "20242025"),
        ("20242025", "20242025"),
        (" 20232024 ", "20232024"),
    ],
)
def test_normalize_season_token(raw: object, expected: str) -> None:
    assert normalize_season_token(raw) == expected


def test_subset_frame_season_holdout_splits_train_test() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2024-10-01", periods=6, freq="D"),
            "season": ["20232024"] * 3 + ["20242025"] * 3,
            "x": range(6),
        }
    )
    target = pd.Series([0, 1, 0, 1, 0, 1])
    cfg = OmegaConf.create(
        {
            "kind": "season_holdout",
            "season_column": "season",
            "holdout_seasons": ["20242025"],
            "train_seasons": None,
        }
    )
    df_o, tgt_o = subset_frame_for_season_holdout(df, target, cfg)
    assert len(df_o) == len(tgt_o) == 6
    tok = df_o["season"].map(normalize_season_token)
    assert (tok == "20232024").sum() == 3
    assert (tok == "20242025").sum() == 3


def test_subset_frame_train_seasons_restricts_train() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2023-10-01", periods=4, freq="D"),
            "season": ["20222023", "20222023", "20232024", "20232024"],
            "x": [1, 2, 3, 4],
        }
    )
    target = pd.Series([0, 1, 0, 1])
    cfg = OmegaConf.create(
        {
            "kind": "season_holdout",
            "season_column": "season",
            "holdout_seasons": ["20232024"],
            "train_seasons": ["20222023"],
        }
    )
    df_o, tgt_o = subset_frame_for_season_holdout(df, target, cfg)
    assert len(df_o) == len(tgt_o) == 4
    tok = df_o["season"].map(normalize_season_token)
    assert (tok == "20222023").sum() == 2
    assert (tok == "20232024").sum() == 2


def test_subset_frame_empty_holdout_raises() -> None:
    df = pd.DataFrame({"season": ["20232024"], "datetime": ["2024-01-01"]})
    target = pd.Series([1])
    cfg = OmegaConf.create(
        {
            "kind": "season_holdout",
            "season_column": "season",
            "holdout_seasons": [],
        }
    )
    with pytest.raises(TrainEvalSplitError):
        subset_frame_for_season_holdout(df, target, cfg)


def test_uses_season_holdout_split_detects_config() -> None:
    cfg = OmegaConf.create(
        {
            "tournament": {
                "name": "nhl",
                "train_eval_split": {"kind": "season_holdout", "holdout_seasons": ["20242025"]},
            }
        }
    )
    assert uses_season_holdout_split(cfg) is True

    cfg2 = OmegaConf.create({"tournament": {"name": "uel_kz_1"}})
    assert uses_season_holdout_split(cfg2) is False
