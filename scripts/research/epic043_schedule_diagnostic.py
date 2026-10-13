"""Диагностика игр лиги рядом с UCL/UEL по нормированным коэффициентам."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


def prepare_team_games(source: pd.DataFrame) -> pd.DataFrame:
    """Развернуть матчи на команды и рассчитать наблюдаемый календарь и очки."""
    events = source.copy()
    events["datetime"] = pd.to_datetime(events["datetime"], utc=True)
    events = events.sort_values(["datetime", "match_id"])
    sides = []
    for side, team_column in (("home", "home_team_id"), ("away", "away_team_id")):
        sides.append(events.assign(team_id=events[team_column], side=side))
    games = pd.concat(sides, ignore_index=True).sort_values(["team_id", "datetime", "match_id"])
    games["euro_date"] = games.datetime.where(games.competition_code.isin(["UCL", "UEL"]))
    groups = games.groupby("team_id", sort=False)
    games["next_euro_date"] = groups.euro_date.bfill()
    games["previous_euro_date"] = groups.euro_date.ffill()
    games["days_to_euro"] = (games.next_euro_date - games.datetime).dt.total_seconds() / 86400
    games["days_after_euro"] = (
        games.datetime - games.previous_euro_date
    ).dt.total_seconds() / 86400
    games["before_euro"] = games.days_to_euro.between(1, 4)
    games["after_euro"] = games.days_after_euro.between(1, 4)
    odds = games[["odd_home", "odd_draw", "odd_away"]].to_numpy(dtype=float)
    valid: Any = cast(Any, np.isfinite(odds)).all(axis=1) & cast(Any, odds > 1).all(axis=1)
    inverse = np.divide(1.0, odds, out=np.zeros_like(odds), where=valid[:, None])
    probabilities = np.divide(
        inverse,
        inverse.sum(axis=1, keepdims=True),
        out=np.zeros_like(inverse),
        where=valid[:, None],
    )
    home = games.side.eq("home").to_numpy()
    home_win = games.home_goals_all.to_numpy() > games.away_goals_all.to_numpy()
    draw = games.home_goals_all.to_numpy() == games.away_goals_all.to_numpy()
    games["actual_points"] = np.where(draw, 1 / 3, np.where(home == home_win, 1.0, 0.0))
    games["market_points"] = np.where(
        home,
        probabilities[:, 0] + probabilities[:, 1] / 3,
        probabilities[:, 2] + probabilities[:, 1] / 3,
    )
    games["residual"] = games.actual_points - games.market_points
    return cast(
        pd.DataFrame,
        games.loc[
            ~games.competition_code.isin(["UCL", "UEL"])
            & games.datetime.ge("2018-07-01")
            & games.datetime.lt("2025-07-01")
            & games.home_goals_all.notna()
            & games.away_goals_all.notna()
            & valid
        ].copy(),
    )


def matched_effect(games: pd.DataFrame, flag: str, *, repeats: int = 2000) -> dict[str, Any]:
    """Сравнить остатки внутри команды-сезона и оценить кластерный интервал."""
    grouped = games.groupby(["team_id", "season_id", flag]).residual.agg(["mean", "size"])
    means = grouped["mean"].unstack(flag).dropna()
    sizes = grouped["size"].unstack(flag).loc[means.index]
    differences = (means[True] - means[False]).to_numpy()
    weights = sizes[True].to_numpy()
    rng = np.random.default_rng(43)
    draws = rng.integers(0, len(differences), size=(repeats, len(differences)))
    samples = np.average(differences[draws], weights=weights[draws], axis=1)
    exposed = games.loc[games[flag]]
    control = games.loc[~games[flag]]
    return {
        "exposed_n": int(len(exposed)),
        "control_n": int(len(control)),
        "exposed_actual": float(exposed.actual_points.mean()),
        "exposed_market": float(exposed.market_points.mean()),
        "exposed_residual": float(exposed.residual.mean()),
        "control_residual": float(control.residual.mean()),
        "matched_team_seasons": int(len(differences)),
        "matched_effect": float(np.average(differences, weights=weights)),
        "matched_ci95": np.quantile(samples, [0.025, 0.975]).tolist(),
    }


def main() -> None:
    """Сохранить воспроизводимые разрезы календаря."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    columns = [
        "match_id",
        "datetime",
        "competition_code",
        "season_id",
        "home_team_id",
        "away_team_id",
        "home_goals_all",
        "away_goals_all",
        "odd_home",
        "odd_draw",
        "odd_away",
    ]
    games = prepare_team_games(pd.read_csv(args.source, usecols=columns))
    result = {
        "team_games": int(len(games)),
        "before_euro": matched_effect(games, "before_euro"),
        "after_euro": matched_effect(games, "after_euro"),
        "before_by_competition": {
            key: {"n": int(len(group)), "residual": float(group.residual.mean())}
            for key, group in games.loc[games.before_euro].groupby("competition_code")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
