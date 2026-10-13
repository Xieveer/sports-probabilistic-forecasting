"""Калибровка и турнирные разрезы сохранённых временных предсказаний."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


def summarize(group: pd.DataFrame) -> dict[str, Any]:
    """Посчитать ошибки 1X2 и доходность единственной ставки на матч."""
    probabilities = group[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    truth = group.truth.to_numpy(dtype=int)
    odds = group[["odd_home", "odd_draw", "odd_away"]].to_numpy(dtype=float)
    valid: Any = cast(Any, np.isfinite(odds)).all(axis=1) & cast(Any, odds > 1).all(axis=1)
    edges = np.full_like(probabilities, -np.inf)
    edges[valid] = probabilities[valid] - 1 / odds[valid]
    choice = edges.argmax(axis=1)
    selected = edges[np.arange(len(group)), choice] > 0.05
    bet_rows = np.flatnonzero(selected)
    hits = truth[bet_rows] == choice[bet_rows]
    returns = hits * odds[bet_rows, choice[bet_rows]] - 1
    chosen_p = probabilities[bet_rows, choice[bet_rows]]
    result: dict[str, Any] = {
        "n": int(len(group)),
        "logloss": float(-np.log(probabilities[np.arange(len(group)), truth]).mean()),
        "brier": float(
            cast(Any, np.sum((probabilities - cast(Any, np.eye(3))[truth]) ** 2, axis=1)).mean()
        ),
        "bets": int(len(bet_rows)),
        "roi": float(returns.mean()) if len(returns) else None,
        "selected_p_mean": float(chosen_p.mean()) if len(chosen_p) else None,
        "selected_hit_rate": float(hits.mean()) if len(hits) else None,
        "selected_gap": float((hits - chosen_p).mean()) if len(hits) else None,
    }
    result["all_by_outcome"] = {
        label: {
            "p_mean": float(probabilities[:, index].mean()),
            "frequency": float((truth == index).mean()),
            "ece_10_bins": float(
                sum(
                    abs((truth[mask] == index).mean() - probabilities[mask, index].mean())
                    * mask.mean()
                    for lower, upper in cast(
                        Any, zip(np.linspace(0, 0.9, 10), np.linspace(0.1, 1, 10), strict=True)
                    )
                    for mask in [
                        (probabilities[:, index] >= lower) & (probabilities[:, index] < upper)
                    ]
                    if mask.any()
                )
            ),
        }
        for index, label in enumerate(("P1", "X", "P2"))
    }
    result["selected_by_outcome"] = {
        label: {
            "bets": int(len(rows)),
            "p_mean": float(probabilities[rows, index].mean()) if len(rows) else None,
            "hit_rate": float((truth[rows] == index).mean()) if len(rows) else None,
            "gap": float((truth[rows] == index).mean() - probabilities[rows, index].mean())
            if len(rows)
            else None,
        }
        for index, label in enumerate(("P1", "X", "P2"))
        for rows in [cast(Any, bet_rows)[choice[bet_rows] == index]]
    }
    bins = [0.0, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
    result["selected_by_probability_bin"] = {
        f"[{lower:.1f},{upper:.1f})": {
            "bets": int(mask.sum()),
            "p_mean": float(chosen_p[mask].mean()) if mask.any() else None,
            "hit_rate": float(hits[mask].mean()) if mask.any() else None,
        }
        for lower, upper in zip(bins[:-1], bins[1:], strict=True)
        for mask in [(chosen_p >= lower) & (chosen_p < upper)]
    }
    return result


def main() -> None:
    """Сохранить турнирные и калибровочные таблицы."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = pd.read_csv(args.trace)
    output: dict[str, Any] = {}
    for variant, rows in frame.groupby("variant"):
        output[str(variant)] = {
            "overall": summarize(rows),
            "by_competition": {
                str(code): summarize(group) for code, group in rows.groupby("competition_code")
            },
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value["overall"] for key, value in output.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
