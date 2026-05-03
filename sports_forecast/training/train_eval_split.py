"""
Train / evaluation splits configurable per tournament (Hydra).

Supports temporal holds defined by **calendar seasons** (e.g. NHL ``season`` column),
so baseline metrics align with full-season holdout rather than a trailing fraction.

Phase C (OT markets): keep separate Hydra runs via ``market`` / ``market_spec``;
do not encode market type into split logic here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class TrainEvalSplitError(Exception):
    """Raised when tournament train/eval split config or data is invalid."""


def normalize_season_token(value: Any) -> str:
    """Normalize a season identifier for set comparisons.

    Parquet/API may store NHL SEASON_ID as int (``20242025``) or string.

    Args:
        value: Raw cell value from ``season`` (or similar).

    Returns:
        Normalized string token; empty string for missing/invalid scalars.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()


def subset_frame_for_season_holdout(
    df: pd.DataFrame,
    target: pd.Series,
    train_eval_cfg: DictConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    """Restrict ``df`` / ``target`` to rows used as train or season-holdout test.

    Rows outside configured seasons are dropped with a warning (e.g. NA ``season``).

    Args:
        df: Sorted training frame (must contain season column when configured).
        target: Target aligned to ``df`` by row position.
        train_eval_cfg: ``cfg.tournament.train_eval_split`` with ``kind: season_holdout``.

    Returns:
        Filtered ``(df, target)`` with reset indices.

    Raises:
        TrainEvalSplitError: Missing columns, empty train/test, or bad config.
    """
    kind = OmegaConf.select(train_eval_cfg, "kind", default=None)
    if kind != "season_holdout":
        raise TrainEvalSplitError(
            f"subset_frame_for_season_holdout expects kind=season_holdout, got {kind!r}"
        )

    season_col = OmegaConf.select(train_eval_cfg, "season_column", default="season")
    if season_col not in df.columns:
        raise TrainEvalSplitError(f"season_column {season_col!r} not in dataframe columns")

    if OmegaConf.is_missing(train_eval_cfg, "holdout_seasons"):
        raise TrainEvalSplitError("train_eval_split.holdout_seasons is required for season_holdout")
    raw_holdout = train_eval_cfg["holdout_seasons"]
    if raw_holdout is None:
        raise TrainEvalSplitError("train_eval_split.holdout_seasons is required for season_holdout")

    holdout_tokens = {
        normalize_season_token(x) for x in list(raw_holdout) if normalize_season_token(x)
    }
    if not holdout_tokens:
        raise TrainEvalSplitError("holdout_seasons resolved to an empty set")

    raw_train_only = (
        None
        if OmegaConf.is_missing(train_eval_cfg, "train_seasons")
        else train_eval_cfg.get("train_seasons")
    )
    train_allow: set[str] | None = None
    if raw_train_only is not None:
        train_allow = {
            normalize_season_token(x) for x in list(raw_train_only) if normalize_season_token(x)
        }
        if not train_allow:
            raise TrainEvalSplitError("train_seasons was set but resolved to an empty set")

    season_tokens = df[season_col].map(normalize_season_token)
    non_empty = season_tokens != ""
    test_mask = non_empty & season_tokens.isin(holdout_tokens)
    train_mask = non_empty & ~season_tokens.isin(holdout_tokens)
    if train_allow is not None:
        train_mask = train_mask & season_tokens.isin(train_allow)

    keep_mask = train_mask | test_mask
    dropped = int((~keep_mask).sum())
    if dropped:
        logger.warning(
            "Season holdout split: dropping %d rows (NA/out-of-scope seasons by config)",
            dropped,
        )

    df_f = df.loc[keep_mask].reset_index(drop=True)
    tgt_f = target.loc[keep_mask].reset_index(drop=True)

    train_kept = train_mask.loc[keep_mask].reset_index(drop=True)
    test_kept = test_mask.loc[keep_mask].reset_index(drop=True)
    n_train = int(train_kept.sum())
    n_test = int(test_kept.sum())
    if n_train == 0 or n_test == 0:
        raise TrainEvalSplitError(
            f"Season holdout produced empty train or test (train={n_train}, test={n_test}). "
            f"Check holdout_seasons={sorted(holdout_tokens)!r} vs data."
        )

    logger.info(
        "Season holdout split: train_rows=%d test_rows=%d holdout=%s",
        n_train,
        n_test,
        sorted(holdout_tokens),
    )

    return df_f, tgt_f


def uses_season_holdout_split(cfg: DictConfig) -> bool:
    """Return True if tournament requests ``season_holdout`` train/eval split."""
    if not hasattr(cfg, "tournament"):
        return False
    te = cfg.tournament.get("train_eval_split", None)
    if te is None:
        return False
    kind = OmegaConf.select(te, "kind", default=None)
    return bool(kind == "season_holdout")
