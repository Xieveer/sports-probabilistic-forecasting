"""Одна ставка на матч рынка П1/Х/П2 по максимальному edge."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.betting.simulator import BettingSimulator
from sports_forecast.training.probability_metrics import (
    audit_long_1x2_probabilities,
    evaluate_multiclass_probabilities,
)


OUTCOMES = ("home_win", "draw", "away_win")
ODDS_COLUMNS = ("odd_home", "odd_draw", "odd_away")


def evaluate_1x2_betting(
    events: pd.DataFrame,
    target: pd.Series,
    probabilities: np.ndarray,
    *,
    is_long: bool,
    classes: np.ndarray | None,
    min_edge_threshold: float,
    flat_stake: float,
    initial_bankroll: float,
    sweep_thresholds: list[float] | None = None,
) -> dict[str, Any]:
    """Оценить один выбранный исход на матч и сохранить знаменатель всего holdout.

    Для long-модели отрицательный остаток ничьей исключает матч из ставок.
    Такие матчи остаются в знаменателе покрытия и измеряются отдельно.
    """
    if "id" not in events:
        raise ValueError("1X2 требует id")
    if len(events) != len(target):
        raise ValueError("Таргет и события имеют разную длину")
    unique = events.drop_duplicates("id").set_index("id", drop=False)
    if events["id"].isna().any():
        raise ValueError("1X2 содержит пустой ID события")
    truth = pd.Series(np.nan, index=unique.index, dtype=float)
    distribution = pd.DataFrame(np.nan, index=unique.index, columns=OUTCOMES)
    rejected_count = 0

    if is_long:
        if "is_home" not in events:
            raise ValueError("Long 1X2 требует is_home")
        available_odds = [column for column in ODDS_COLUMNS if column in events]
        if available_odds and (
            events.groupby("id", sort=False)[available_odds].nunique(dropna=False).gt(1).any().any()
        ):
            raise ValueError("Long 1X2 содержит разные коэффициенты у сторон матча")
        sides = events[["id", "is_home"]].copy()
        sides["win"] = np.asarray(target, dtype=int)
        wins = sides.pivot(index="id", columns="is_home", values="win")
        if not {0, 1} <= set(wins.columns) or wins[[0, 1]].isna().any().any():
            raise ValueError("Long 1X2 требует обе стороны каждого матча")
        if ((wins[0] + wins[1]) > 1).any():
            raise ValueError("Long 1X2 содержит две победы в одном матче")
        truth.loc[wins.index] = np.select(
            [wins[1].to_numpy() == 1, wins[0].to_numpy() == 1], [0, 2], default=1
        )
        valid, rejected = audit_long_1x2_probabilities(events, np.asarray(probabilities)[:, 1])
        distribution.loc[valid.index, :] = valid.loc[:, list(OUTCOMES)].to_numpy()
        rejected_count = len(rejected)
    else:
        values = np.asarray(probabilities, dtype=float)
        if classes is None or values.shape != (len(events), 3):
            raise ValueError("Wide 1X2 требует три вероятности и classes_ модели")
        if events["id"].duplicated().any():
            raise ValueError("Wide 1X2 содержит повторный ID события")
        order = [list(classes).index(label) for label in (0, 1, 2)]
        evaluate_multiclass_probabilities(np.asarray(target), values, classes)
        truth.loc[events["id"].to_numpy()] = np.asarray(target, dtype=int)
        distribution.loc[events["id"].to_numpy(), :] = values[:, order]

    odds = unique.reindex(columns=ODDS_COLUMNS).apply(pd.to_numeric, errors="coerce").to_numpy()
    probs = distribution.to_numpy(dtype=float)
    valid_odds = np.isfinite(odds).all(axis=1) & (odds > 1).all(axis=1)
    valid_probs = np.logical_and(np.all(np.isfinite(probs), axis=1), np.all(probs >= 0, axis=1))
    eligible = valid_odds & valid_probs
    edges = np.full_like(probs, -np.inf)
    edges[eligible] = probs[eligible] - 1 / odds[eligible]
    choice = edges.argmax(axis=1)
    row = np.arange(len(unique))
    selected_p = np.where(eligible, probs[row, choice], 0.0)
    selected_odds = np.where(eligible, odds[row, choice], 2.0)
    selected_target = (truth.to_numpy(dtype=int) == choice).astype(int)

    simulator = BettingSimulator(
        initial_bankroll=initial_bankroll,
        flat_stake=flat_stake,
        stake_strategy="flat",
        min_edge_threshold=min_edge_threshold,
    )
    result = simulator.simulate(
        selected_target,
        selected_p,
        selected_odds,
        bet_eligible_mask=eligible,
        return_event_trace=True,
    )
    trace = result.event_trace
    if trace is not None:
        trace.insert(0, "id", unique.index.to_numpy())
        trace.insert(1, "outcome", [OUTCOMES[int(index)] for index in choice])
    outcome_counts = {
        outcome: int(np.count_nonzero(result.bet_mask & (choice == index)))
        for index, outcome in enumerate(OUTCOMES)
    }
    sweep = None
    if sweep_thresholds is not None:
        sweep = simulator.sweep_thresholds(
            selected_target[eligible],
            np.compress(eligible, selected_p),
            np.compress(eligible, selected_odds),
            sweep_thresholds,
        )
    valid_market = distribution.notna().all(axis=1)
    market_metrics = (
        evaluate_multiclass_probabilities(
            truth.loc[valid_market].to_numpy(dtype=int),
            distribution.loc[valid_market].to_numpy(dtype=float),
            np.array([0, 1, 2]),
        )
        if valid_market.any()
        else {}
    )
    return {
        "n_total_events": result.n_total_events,
        "n_bets": result.n_bets,
        "turnover_units": result.turnover_units,
        "coverage": result.coverage,
        "profit_units": result.profit_units,
        "roi": result.roi,
        "avg_profit_per_bet": result.avg_profit_per_bet,
        "avg_edge": result.avg_edge,
        "avg_ev": result.avg_ev,
        "ev_sum_units": result.ev_sum_units,
        "ev_realization": result.ev_realization,
        "hit_rate": result.hit_rate,
        "num_wins": result.num_wins,
        "max_drawdown_units": result.max_drawdown_units,
        "max_drawdown_pct": result.max_drawdown_pct,
        "std_return_per_bet": result.std_return_per_bet,
        "sharpe_like": result.sharpe_like,
        "profit_factor": result.profit_factor,
        "avg_odds": result.avg_odds,
        "final_bankroll": result.final_bankroll,
        "equity_curve": result.equity_curve,
        "sweep_df": sweep,
        "cal_table": [],
        "odds_column": ",".join(ODDS_COLUMNS),
        "valid_odds_count": int(valid_odds.sum()),
        "valid_distribution_count": int(valid_market.sum()),
        "rejected_distribution_count": rejected_count,
        "market_metrics": market_metrics,
        "bet_outcome_counts": outcome_counts,
        "bet_trace": trace,
        "bet_trace_csv_path": None,
    }
