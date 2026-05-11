"""Walk-forward training loop: refit each calendar step with fixed hyperparameters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from omegaconf import DictConfig, OmegaConf
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from sports_forecast.betting.odds import extract_betting_odds
from sports_forecast.betting.simulator import BettingSimulator
from sports_forecast.training.base import BaseModel
from sports_forecast.training.walk_forward.slicer import WalkForwardSlicer
from sports_forecast.utils.log_config import get_logger
from sports_forecast.utils.metrics import (
    compute_expected_calibration_error,
    compute_max_calibration_error,
)


logger = get_logger(__name__)


@dataclass
class WalkForwardResult:
    """Outputs of :class:`WalkForwardRunner`.

    Attributes:
        per_step_metrics: One dict per WF step (ML + optional betting slice metrics).
        per_step_predictions: List of ``predict_proba[:, 1]`` arrays per step (OOS rows only).
        cumulative_test_df: All OOS predictions with ``wf_step`` column.
        final_model: Model refit on all data (train core + full OOS) after the last step.
        cumulative_business_metrics: Betting metrics on concatenated valid odds events
            (single :meth:`BettingSimulator.simulate` run).
        cumulative_bet_trace_path: Path to ``cumulative_bet_trace.csv`` if written.
        aggregate_ml_metrics: ML metrics on cumulative OOS predictions.
    """

    per_step_metrics: list[dict[str, Any]]
    per_step_predictions: list[np.ndarray]
    cumulative_test_df: pd.DataFrame
    final_model: BaseModel
    cumulative_business_metrics: dict[str, Any] = field(default_factory=dict)
    cumulative_bet_trace_path: Path | None = None
    aggregate_ml_metrics: dict[str, float] = field(default_factory=dict)


def _ml_metrics(y_true: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(proba, dtype=float)
    y_pred = (p >= 0.5).astype(int)
    metrics: dict[str, float] = {}
    try:
        metrics["logloss"] = float(log_loss(y, p))
    except Exception:
        metrics["logloss"] = 0.0
    try:
        metrics["auc"] = float(roc_auc_score(y, p))
    except Exception:
        metrics["auc"] = 0.0
    try:
        metrics["accuracy"] = float(accuracy_score(y, y_pred))
    except Exception:
        metrics["accuracy"] = 0.0
    try:
        metrics["brier"] = float(brier_score_loss(y, p))
    except Exception:
        metrics["brier"] = 0.0
    try:
        metrics["ece"] = float(compute_expected_calibration_error(y, p))
    except Exception:
        metrics["ece"] = 0.0
    try:
        metrics["mce"] = float(compute_max_calibration_error(y, p))
    except Exception:
        metrics["mce"] = 0.0
    return metrics


class WalkForwardRunner:
    """Run expanding-window month steps: fit → predict OOS slice → augment (via slicer masks)."""

    def __init__(
        self,
        cfg: DictConfig,
        create_model: Callable[[dict[str, Any] | None], BaseModel],
    ) -> None:
        self._cfg = cfg
        self._create_model = create_model

    def run(
        self,
        *,
        combined_df: pd.DataFrame,
        features: pd.DataFrame,
        target: pd.Series,
        feature_names: list[str],
        best_params: dict[str, Any] | None,
        init_train_end: pd.Timestamp,
        time_col: str,
        artifact_dir: Path,
    ) -> WalkForwardResult:
        """Execute walk-forward on row-aligned frames (train block before test block in ``combined_df``).

        Args:
            combined_df: Train rows first, then test/holdout rows (same order as features).
            features: Same length as ``combined_df``.
            target: Same length as ``combined_df``.
            feature_names: Logging aid (already reflected in ``features`` columns).
            best_params: Optuna-merged params for each refit when ``reuse_optuna_params``;
                otherwise ``None`` so only config defaults apply.
            init_train_end: Inclusive end of the core training window (typically
                ``max(datetime)`` over the train split).
            time_col: Datetime column in ``combined_df``.
            artifact_dir: Output directory for ``cumulative_bet_trace.csv``.

        Returns:
            :class:`WalkForwardResult`.

        Raises:
            RuntimeError: If the slicer yields no step.
            ValueError: If lengths mismatch.
        """
        _ = feature_names
        if len(combined_df) != len(features) or len(features) != len(target):
            msg = "combined_df, features, target must have identical row counts"
            raise ValueError(msg)

        frequency = str(OmegaConf.select(self._cfg, "walk_forward.frequency", default="month"))
        reuse_optuna = bool(
            OmegaConf.select(self._cfg, "walk_forward.reuse_optuna_params", default=True)
        )
        step_params = best_params if reuse_optuna else None

        init_end = pd.Timestamp(init_train_end)
        slicer = WalkForwardSlicer(combined_df, time_col, frequency, init_end)

        per_step_metrics: list[dict[str, Any]] = []
        per_step_predictions: list[np.ndarray] = []
        cum_rows: list[pd.DataFrame] = []

        betting_cfg = self._cfg.get("betting", {})
        bookmaker_cfg = self._cfg.get("bookmaker", {})
        market_spec = self._cfg.market_spec

        cumulative_y: list[np.ndarray] = []
        cumulative_p: list[np.ndarray] = []
        cumulative_odds: list[np.ndarray] = []
        trace_parts: list[pd.DataFrame] = []

        model: BaseModel | None = None
        for step_i, train_mask, test_mask in slicer:
            train_feats = features.loc[train_mask].reset_index(drop=True)
            y_tr = target.loc[train_mask].reset_index(drop=True)
            test_feats = features.loc[test_mask].reset_index(drop=True)
            y_te = target.loc[test_mask].reset_index(drop=True)
            df_te = combined_df.loc[test_mask].reset_index(drop=True)

            model = self._create_model(step_params)
            model.fit(train_feats, y_tr)
            proba = model.predict_proba(test_feats)[:, 1]

            ml_i = _ml_metrics(np.asarray(y_te), np.asarray(proba))
            row: dict[str, Any] = {"wf_step": step_i, **{f"ml_{k}": v for k, v in ml_i.items()}}
            per_step_metrics.append(row)
            per_step_predictions.append(np.asarray(proba, dtype=float))

            idx = np.where(test_mask)[0]
            chunk = pd.DataFrame(
                {
                    "wf_step": step_i,
                    "row_index": idx,
                    "y_true": np.asarray(y_te, dtype=float),
                    "proba_pos": np.asarray(proba, dtype=float),
                }
            )
            if time_col in df_te.columns:
                chunk[time_col] = df_te[time_col].to_numpy()
            cum_rows.append(chunk)

            if betting_cfg.get("enabled", False):
                odds = extract_betting_odds(df_te, market_spec, bookmaker_cfg)
                valid = odds.notna() & (odds > 1.0)
                if int(valid.sum()) > 0:
                    yt = np.asarray(y_te.loc[valid], dtype=float)
                    pr = np.asarray(proba[valid.to_numpy()], dtype=float)
                    od = np.asarray(odds.loc[valid], dtype=float)
                    cumulative_y.append(yt)
                    cumulative_p.append(pr)
                    cumulative_odds.append(od)

                    simulator = BettingSimulator(
                        initial_bankroll=betting_cfg.get("initial_bankroll", 1000.0),
                        stake_strategy=betting_cfg.get("stake_strategy", "flat"),
                        flat_stake=betting_cfg.get("flat_stake", 10.0),
                        kelly_fraction=betting_cfg.get("kelly_fraction", 0.25),
                        min_edge_threshold=betting_cfg.get(
                            "min_edge_threshold",
                            betting_cfg.get("min_value_threshold", 0.05),
                        ),
                        max_stake_fraction=betting_cfg.get("max_stake_fraction", 0.1),
                    )
                    res = simulator.simulate(yt, pr, od, return_event_trace=True)
                    row["betting_n_bets"] = res.n_bets
                    row["betting_roi"] = res.roi
                    row["betting_profit_units"] = res.profit_units
                    row["betting_sharpe_like"] = res.sharpe_like
                    row["betting_max_drawdown_units"] = res.max_drawdown_units
                    if res.event_trace is not None and len(res.event_trace) > 0:
                        tr = res.event_trace.copy()
                        tr.insert(0, "wf_step", step_i)
                        trace_parts.append(tr)

        if model is None:
            raise RuntimeError(
                "Walk-forward produced no steps — check OOS date range vs init_train_end "
                "and non-empty holdout."
            )

        cumulative_test_df = pd.concat(cum_rows, ignore_index=True) if cum_rows else pd.DataFrame()

        y_all = np.concatenate(cumulative_y) if cumulative_y else np.array([])
        p_all = np.concatenate(cumulative_p) if cumulative_p else np.array([])
        o_all = np.concatenate(cumulative_odds) if cumulative_odds else np.array([])

        cum_business: dict[str, Any] = {}
        trace_path: Path | None = None
        if betting_cfg.get("enabled", False) and len(y_all) > 0:
            simulator = BettingSimulator(
                initial_bankroll=betting_cfg.get("initial_bankroll", 1000.0),
                stake_strategy=betting_cfg.get("stake_strategy", "flat"),
                flat_stake=betting_cfg.get("flat_stake", 10.0),
                kelly_fraction=betting_cfg.get("kelly_fraction", 0.25),
                min_edge_threshold=betting_cfg.get(
                    "min_edge_threshold",
                    betting_cfg.get("min_value_threshold", 0.05),
                ),
                max_stake_fraction=betting_cfg.get("max_stake_fraction", 0.1),
            )
            agg = simulator.simulate(y_all, p_all, o_all, return_event_trace=False)
            cum_business = {
                "n_bets": agg.n_bets,
                "roi": agg.roi,
                "profit_units": agg.profit_units,
                "sharpe_like": agg.sharpe_like,
                "max_drawdown_units": agg.max_drawdown_units,
                "max_drawdown_pct": agg.max_drawdown_pct,
                "n_total_events": agg.n_total_events,
                "turnover_units": agg.turnover_units,
                "coverage": agg.coverage,
                "hit_rate": agg.hit_rate,
                "profit_factor": agg.profit_factor,
                "num_wins": agg.num_wins,
            }
            if trace_parts:
                full_trace = pd.concat(trace_parts, ignore_index=True)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                trace_path = artifact_dir / "cumulative_bet_trace.csv"
                full_trace.to_csv(trace_path, index=False)

        aggregate_ml: dict[str, float] = {}
        if not cumulative_test_df.empty and "y_true" in cumulative_test_df.columns:
            aggregate_ml = _ml_metrics(
                cumulative_test_df["y_true"].to_numpy(dtype=float),
                cumulative_test_df["proba_pos"].to_numpy(dtype=float),
            )

        final_model = self._create_model(step_params)
        final_model.fit(features, target)

        return WalkForwardResult(
            per_step_metrics=per_step_metrics,
            per_step_predictions=per_step_predictions,
            cumulative_test_df=cumulative_test_df,
            final_model=final_model,
            cumulative_business_metrics=cum_business,
            cumulative_bet_trace_path=trace_path,
            aggregate_ml_metrics=aggregate_ml,
        )
