"""Circular block bootstrap for betting trace metrics (temporal dependence-aware uncertainty).

Resamples sequences of **placed bets** from a simulator ``event_trace`` / ``test_bet_trace``-style
DataFrame and builds percentile confidence intervals for ROI and related statistics.

When to use: after training or walk-forward, on the final concatenated bet list, to avoid
i.i.d. bootstrap underestimation of variance under autocorrelation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sports_forecast.betting.simulator import BettingSimulator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class MetricBootstrapStats:
    """Bootstrap summary for one scalar metric.

    Attributes:
        mean: Mean of bootstrap replicate values.
        ci_lower: Lower endpoint of percentile CI at ``confidence_level``.
        ci_upper: Upper endpoint of percentile CI at ``confidence_level``.
        se: Standard deviation of bootstrap replicates (Bessel-corrected when B>1).
        n_resamples: Number of bootstrap replicates B.
    """

    mean: float
    ci_lower: float
    ci_upper: float
    se: float
    n_resamples: int


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of :meth:`BlockBootstrap.run`.

    Attributes:
        metrics: Map metric name → bootstrap statistics.
        n_resamples: Configured number of replicates (also duplicated per metric).
        confidence_level: Nominal CI level used for endpoints.
    """

    metrics: dict[str, MetricBootstrapStats]
    n_resamples: int
    confidence_level: float

    def summary_dataframe(self) -> pd.DataFrame:
        """Return a long table: metric, mean, ci_lower, ci_upper, se, n_resamples."""
        rows: list[dict[str, float | int | str]] = []
        for name, stat in sorted(self.metrics.items()):
            rows.append(
                {
                    "metric": name,
                    "mean": stat.mean,
                    "ci_lower": stat.ci_lower,
                    "ci_upper": stat.ci_upper,
                    "se": stat.se,
                    "n_resamples": stat.n_resamples,
                }
            )
        return pd.DataFrame(rows)


def _placed_bets_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask for rows that correspond to placed bets."""
    if "bet_placed" in df.columns:
        return df["bet_placed"].astype(bool)
    if "stake" in df.columns:
        return pd.to_numeric(df["stake"], errors="coerce").fillna(0.0) > 0
    return pd.Series(False, index=df.index)


def _compute_metrics_for_resample(
    stakes: np.ndarray,
    profits: np.ndarray,
    y_true: np.ndarray,
    *,
    initial_bankroll: float,
) -> dict[str, float]:
    """Compute betting metrics for one resampled bet sequence (aligned arrays)."""
    n_bets = int(len(profits))
    turnover = float(np.sum(stakes))
    profit_units = float(np.sum(profits))
    roi = (profit_units / turnover * 100.0) if turnover > 1e-12 else 0.0
    wins = float(np.sum(y_true == 1))
    hit_rate = wins / n_bets if n_bets > 0 else 0.0
    if n_bets > 1:
        std_ret = float(np.std(profits, ddof=1))
    elif n_bets == 1:
        std_ret = 0.0
    else:
        std_ret = 0.0
    mean_ret = float(np.mean(profits)) if n_bets > 0 else 0.0
    sharpe_like = mean_ret / std_ret if std_ret > 1e-9 else 0.0

    equity: list[float] = [float(initial_bankroll)]
    bankroll = float(initial_bankroll)
    for k in range(n_bets):
        bankroll += float(profits[k])
        equity.append(bankroll)
    max_dd_units, max_dd_pct = BettingSimulator._compute_drawdown(equity)

    return {
        "roi": float(roi),
        "profit_units": float(profit_units),
        "n_bets": float(n_bets),
        "sharpe_like": float(sharpe_like),
        "max_drawdown_pct": float(max_dd_pct),
        "hit_rate": float(hit_rate),
        "max_drawdown_units": float(max_dd_units),
    }


def _draw_block_indices(
    n: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator,
) -> list[int]:
    """Build index list of length ``n`` via circular block resampling."""
    if n <= 0:
        return []
    lo = int(min_block)
    hi = int(max_block)
    if lo > hi:
        lo, hi = hi, lo
    out: list[int] = []
    while len(out) < n:
        block_len = int(rng.integers(lo, hi + 1))
        if block_len >= n:
            out.extend(range(n))
            continue
        start = int(rng.integers(0, n))
        for j in range(block_len):
            out.append((start + j) % n)
    return out[:n]


class BlockBootstrap:
    """Circular block bootstrap (Politis–Romano style wrapping) on a bet trace.

    Expects columns compatible with :class:`~sports_forecast.betting.simulator.BettingSimulator`
    event trace: at least ``stake``, ``profit``, ``y_true`` on rows where a bet was placed.
    Rows with ``bet_placed`` false or zero stake are ignored for resampling (stake/profit summary).

    Args:
        bet_trace_df: Full per-event or per-bet trace (only placed rows are used).
        n_resamples: Number of bootstrap replicates B.
        min_block_length: Minimum block length in **number of bets** (inclusive).
        max_block_length: Maximum block length (inclusive).
        seed: RNG seed; ``None`` for non-reproducible draws.
        confidence_level: Nominal mass inside percentile interval (e.g. 0.95).
        initial_bankroll: Starting bankroll for drawdown computation (matches typical simulator default).
    """

    METRIC_KEYS = (
        "roi",
        "profit_units",
        "n_bets",
        "sharpe_like",
        "max_drawdown_pct",
        "hit_rate",
    )

    def __init__(
        self,
        bet_trace_df: pd.DataFrame,
        n_resamples: int = 5000,
        min_block_length: int = 10,
        max_block_length: int = 30,
        seed: int | None = None,
        confidence_level: float = 0.95,
        initial_bankroll: float = 1000.0,
    ) -> None:
        self._df = bet_trace_df
        self._n_resamples = int(n_resamples)
        self._min_block = int(min_block_length)
        self._max_block = int(max_block_length)
        self._seed = seed
        self._confidence_level = float(confidence_level)
        self._initial_bankroll = float(initial_bankroll)

    def run(self) -> BootstrapResult:
        """Run block bootstrap and return per-metric summaries.

        Returns:
            :class:`BootstrapResult`. If there are no placed bets, ``metrics`` is empty
            and a warning is logged (callers should skip MLflow noise).
        """
        if self._n_resamples <= 0:
            logger.warning("BlockBootstrap: n_resamples=%s ≤ 0 — пропуск", self._n_resamples)
            return BootstrapResult(
                metrics={},
                n_resamples=self._n_resamples,
                confidence_level=self._confidence_level,
            )

        placed = self._df.loc[_placed_bets_mask(self._df)].reset_index(drop=True)
        n = len(placed)
        required = {"stake", "profit", "y_true"}
        missing = required - set(placed.columns)
        if missing:
            logger.warning(
                "BlockBootstrap: отсутствуют колонки %s — пропуск",
                sorted(missing),
            )
            return BootstrapResult(
                metrics={},
                n_resamples=self._n_resamples,
                confidence_level=self._confidence_level,
            )

        if n == 0:
            logger.warning("BlockBootstrap: нет строк с размещёнными ставками — пропуск")
            return BootstrapResult(
                metrics={},
                n_resamples=self._n_resamples,
                confidence_level=self._confidence_level,
            )

        stakes = pd.to_numeric(placed["stake"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        profits = pd.to_numeric(placed["profit"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        y_true = pd.to_numeric(placed["y_true"], errors="coerce").fillna(0.0).to_numpy(dtype=float)

        lo = max(1, self._min_block)
        hi = max(lo, self._max_block)
        rng = np.random.default_rng(self._seed)

        alpha = (1.0 - self._confidence_level) / 2.0
        q_low = alpha * 100.0
        q_high = (1.0 - alpha) * 100.0

        replicate_matrix: dict[str, np.ndarray] = {
            k: np.empty(self._n_resamples) for k in self.METRIC_KEYS
        }

        for b in range(self._n_resamples):
            idx = _draw_block_indices(n, lo, hi, rng)
            s = stakes[idx]
            p = profits[idx]
            y = y_true[idx]
            stats = _compute_metrics_for_resample(
                s,
                p,
                y,
                initial_bankroll=self._initial_bankroll,
            )
            for k in self.METRIC_KEYS:
                replicate_matrix[k][b] = stats[k]

        metrics_out: dict[str, MetricBootstrapStats] = {}
        for k in self.METRIC_KEYS:
            arr = replicate_matrix[k]
            metrics_out[k] = MetricBootstrapStats(
                mean=float(np.mean(arr)),
                ci_lower=float(np.percentile(arr, q_low)),
                ci_upper=float(np.percentile(arr, q_high)),
                se=float(np.std(arr, ddof=1)) if self._n_resamples > 1 else 0.0,
                n_resamples=self._n_resamples,
            )

        return BootstrapResult(
            metrics=metrics_out,
            n_resamples=self._n_resamples,
            confidence_level=self._confidence_level,
        )
