"""Unit tests for circular block bootstrap on betting traces."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from sports_forecast.betting.bootstrap import BlockBootstrap


def _make_trace(
    stake: np.ndarray,
    profit: np.ndarray,
    y_true: np.ndarray,
    *,
    bet_placed: bool = True,
) -> pd.DataFrame:
    n = len(profit)
    return pd.DataFrame(
        {
            "bet_placed": [bet_placed] * n,
            "stake": stake,
            "profit": profit,
            "y_true": y_true,
        }
    )


def test_fair_bets_roi_ci_contains_zero() -> None:
    n = 200
    y = np.array([0.0, 1.0] * (n // 2))
    profit = np.where(y == 1, 1.0, -1.0)
    stake = np.ones(n)
    df = _make_trace(stake, profit, y)
    bb = BlockBootstrap(
        df,
        n_resamples=3000,
        min_block_length=8,
        max_block_length=25,
        seed=42,
        confidence_level=0.95,
    )
    roi = bb.run().metrics["roi"]
    assert roi.ci_lower <= 0 <= roi.ci_upper


def test_all_winning_roi_ci_strictly_positive() -> None:
    n = 80
    df = _make_trace(np.ones(n), np.ones(n), np.ones(n))
    bb = BlockBootstrap(
        df,
        n_resamples=2000,
        min_block_length=5,
        max_block_length=15,
        seed=0,
        confidence_level=0.95,
    )
    roi = bb.run().metrics["roi"]
    assert roi.ci_lower > 0 and roi.ci_upper > 0


def test_block_length_exceeds_n_bets_uses_full_sample_block() -> None:
    n = 10
    profit = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    df = _make_trace(np.ones(n), profit, np.asarray(profit > 0, dtype=float))
    res = BlockBootstrap(
        df,
        n_resamples=500,
        min_block_length=100,
        max_block_length=200,
        seed=7,
        confidence_level=0.95,
    ).run()
    turnover = float(n)
    point_roi = float(np.sum(profit) / turnover * 100.0)
    assert abs(res.metrics["roi"].mean - point_roi) < 1e-9


def test_reproducibility_with_seed() -> None:
    n = 60
    rng = np.random.default_rng(99)
    y = rng.integers(0, 2, size=n)
    pnl = np.where(y == 1, 0.8, -1.0)
    df = _make_trace(np.ones(n), pnl, np.asarray(y, dtype=float))
    a = BlockBootstrap(
        df,
        n_resamples=800,
        min_block_length=4,
        max_block_length=12,
        seed=12345,
    ).run()
    b = BlockBootstrap(
        df,
        n_resamples=800,
        min_block_length=4,
        max_block_length=12,
        seed=12345,
    ).run()
    assert a.metrics["roi"].mean == b.metrics["roi"].mean
    assert a.metrics["profit_units"].ci_lower == b.metrics["profit_units"].ci_lower


def test_empty_placed_bets_emits_warning_and_empty_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = pd.DataFrame(
        {
            "bet_placed": [False],
            "stake": [0.0],
            "profit": [0.0],
            "y_true": [0.0],
        }
    )
    caplog.set_level(logging.WARNING, logger="sports_forecast.betting.bootstrap")
    result = BlockBootstrap(df, n_resamples=100, seed=1).run()
    assert result.metrics == {}
    assert any("нет строк" in rec.getMessage() for rec in caplog.records)
