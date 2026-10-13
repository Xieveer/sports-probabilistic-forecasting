"""Парный недельный bootstrap для baseline и Elo в EPIC-043."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


def prepare_trace(path: Path) -> pd.DataFrame:
    """Пересчитать решение о ставке и logloss из сохранённых вероятностей."""
    trace = pd.read_csv(path)
    trace["datetime"] = pd.to_datetime(trace.datetime, utc=True)
    trace["week"] = (
        trace.datetime.dt.floor("D") - pd.to_timedelta(trace.datetime.dt.weekday, unit="D")
    ).dt.strftime("%Y-%m-%d")
    trace["selected"] = False
    trace["profit"] = 0.0
    trace["logloss"] = 0.0
    for variant in ("baseline", "elo"):
        mask = trace.variant.eq(variant).to_numpy()
        subset = trace.loc[mask]
        probabilities = subset[["p_home", "p_draw", "p_away"]].to_numpy(float)
        truth = subset.truth.to_numpy(int)
        odds = subset[["odd_home", "odd_draw", "odd_away"]].to_numpy(float)
        valid: Any = cast(Any, np.isfinite(odds)).all(axis=1) & cast(Any, odds > 1).all(axis=1)
        edges = np.full_like(probabilities, -np.inf)
        edges[valid] = probabilities[valid] - 1.0 / odds[valid]
        choice = edges.argmax(axis=1)
        selected = edges[np.arange(len(subset)), choice] > 0.05
        profit = np.where(
            selected,
            (choice == truth) * odds[np.arange(len(subset)), choice] - 1.0,
            0.0,
        )
        trace.loc[mask, "selected"] = selected
        trace.loc[mask, "profit"] = profit
        trace.loc[mask, "logloss"] = -np.log(probabilities[np.arange(len(subset)), truth])
    return trace


def paired_bootstrap(
    trace: pd.DataFrame, *, repetitions: int = 5000, seed: int = 43
) -> dict[str, object]:
    """Ресемплировать недели внутри каждого сезона, сохраняя пары событий."""
    baseline = trace[trace.variant.eq("baseline")].set_index("id").sort_index()
    elo = trace[trace.variant.eq("elo")].set_index("id").sort_index()
    if not baseline.index.equals(elo.index) or not baseline.truth.equals(elo.truth):
        raise ValueError("Baseline и Elo должны содержать одинаковые события и исходы")
    paired = pd.DataFrame(
        {
            "fold": baseline.fold,
            "week": baseline.week,
            "ll_diff": elo.logloss - baseline.logloss,
            "profit_diff": elo.profit - baseline.profit,
            "baseline_profit": baseline.profit,
            "elo_profit": elo.profit,
            "baseline_bets": baseline.selected.astype(int),
            "elo_bets": elo.selected.astype(int),
        }
    )
    weekly = paired.groupby(["fold", "week"], sort=False).agg(
        n=("ll_diff", "size"),
        ll_diff=("ll_diff", "sum"),
        profit_diff=("profit_diff", "sum"),
        baseline_profit=("baseline_profit", "sum"),
        elo_profit=("elo_profit", "sum"),
        baseline_bets=("baseline_bets", "sum"),
        elo_bets=("elo_bets", "sum"),
    )
    groups = [group.to_numpy(float) for _, group in weekly.groupby(level=0)]
    rng = np.random.default_rng(seed)
    samples = np.empty((repetitions, 4), dtype=float)
    for repetition in range(repetitions):
        totals: Any = np.sum(
            [group[rng.integers(0, len(group), len(group))].sum(axis=0) for group in groups],
            axis=0,
        )
        n, ll_diff, profit_diff, baseline_profit, elo_profit, baseline_bets, elo_bets = totals
        samples[repetition] = [
            ll_diff / n,
            profit_diff,
            baseline_profit / baseline_bets,
            elo_profit / elo_bets,
        ]
    names = ("logloss_diff", "profit_diff_unit_stakes", "baseline_roi", "elo_roi")
    return {
        "weeks": len(weekly),
        "repetitions": repetitions,
        "seed": seed,
        "point": {
            "logloss_diff": float(paired.ll_diff.mean()),
            "profit_diff_unit_stakes": float(paired.profit_diff.sum()),
            "baseline_roi": float(paired.baseline_profit.sum() / paired.baseline_bets.sum()),
            "elo_roi": float(paired.elo_profit.sum() / paired.elo_bets.sum()),
        },
        "ci95": {
            name: [float(value) for value in np.quantile(samples[:, index], [0.025, 0.975])]
            for index, name in enumerate(names)
        },
    }


def main() -> None:
    """Прочитать trace и вывести JSON с парной неопределённостью."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    print(json.dumps(paired_bootstrap(prepare_trace(args.trace)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
