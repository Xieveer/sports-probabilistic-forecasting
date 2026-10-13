"""Разведочные временные сравнения футбольных признаков EPIC-043.

Запуск требует локальные source.csv, train_wide.parquet и features.txt.
Историческое расписание будущих еврокубков здесь является исследовательским
proxy: время публикации календаря источником не подтверждено.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import log_loss


FOLDS = ((2022, 2023), (2023, 2024), (2024, 2025))
EURO_CODES = {"UCL", "UEL"}
CALENDAR_COLUMNS = (
    "home_matches_7d",
    "away_matches_7d",
    "home_matches_14d",
    "away_matches_14d",
    "home_days_since_match",
    "away_days_since_match",
    "home_next_euro_4d",
    "away_next_euro_4d",
)
ELO_COLUMNS = ("home_elo", "away_elo", "elo_diff")
COMP_XG_COLUMNS = ("home_comp_xg_diff_ewm10", "away_comp_xg_diff_ewm10", "comp_xg_diff_ewm10")


def load_source(path: Path) -> pd.DataFrame:
    """Загрузить только поля, необходимые для календаря и Elo."""
    columns = [
        "match_id",
        "datetime",
        "competition_code",
        "home_team_id",
        "away_team_id",
        "home_goals_all",
        "away_goals_all",
        "home_xg_all",
        "away_xg_all",
    ]
    frame = pd.read_csv(path, usecols=columns)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    if frame["match_id"].duplicated().any():
        raise ValueError("Повторные match_id в source")
    return frame.sort_values(["datetime", "match_id"]).reset_index(drop=True)


def build_elo_features(source: pd.DataFrame) -> pd.DataFrame:
    """Считать рейтинг до события, обновляя его только по завершённым матчам."""
    ratings: dict[int, float] = defaultdict(lambda: 1500.0)
    rows: list[tuple[int, float, float, float]] = []
    for raw_event in source.itertuples(index=False):
        event = cast(Any, raw_event)
        home_id, away_id = int(event.home_team_id), int(event.away_team_id)
        home_rating, away_rating = ratings[home_id], ratings[away_id]
        rows.append((int(event.match_id), home_rating, away_rating, home_rating - away_rating))
        if pd.isna(event.home_goals_all) or pd.isna(event.away_goals_all):
            continue
        expected = 1.0 / (1.0 + 10.0 ** ((away_rating - home_rating - 65.0) / 400.0))
        actual = 1.0 if event.home_goals_all > event.away_goals_all else 0.0
        if event.home_goals_all == event.away_goals_all:
            actual = 0.5
        change = 20.0 * (actual - expected)
        ratings[home_id] += change
        ratings[away_id] -= change
    return pd.DataFrame(rows, columns=["id", *ELO_COLUMNS])


def build_calendar_features(source: pd.DataFrame) -> pd.DataFrame:
    """Считать прошлую нагрузку и ближайший матч UCL/UEL по двум сторонам."""
    participants = pd.concat(
        [
            source[["match_id", "datetime", "competition_code", "home_team_id"]]
            .rename(columns={"home_team_id": "team_id"})
            .assign(side="home"),
            source[["match_id", "datetime", "competition_code", "away_team_id"]]
            .rename(columns={"away_team_id": "team_id"})
            .assign(side="away"),
        ],
        ignore_index=True,
    ).sort_values(["team_id", "datetime", "match_id"])
    rows: list[tuple[int, str, float, float, float, float]] = []
    for _team_id, group in participants.groupby("team_id", sort=False):
        euro_dates = pd.DatetimeIndex(
            group.loc[group.competition_code.isin(EURO_CODES), "datetime"]
        )
        past: deque[pd.Timestamp] = deque()
        last_match: pd.Timestamp | None = None
        for raw_event in group.itertuples(index=False):
            event = cast(Any, raw_event)
            current = event.datetime
            while past and (current - past[0]).total_seconds() > 14 * 86400:
                past.popleft()
            days_since = (
                (current - last_match).total_seconds() / 86400 if last_match is not None else np.nan
            )
            n_7 = sum((current - previous).total_seconds() <= 7 * 86400 for previous in past)
            n_14 = len(past)
            next_pos = euro_dates.searchsorted(current, side="right")
            next_4d = 0.0
            if next_pos < len(euro_dates):
                days_to = (euro_dates[next_pos] - current).total_seconds() / 86400
                next_4d = float(1.0 <= days_to <= 4.0)
            rows.append(
                (int(event.match_id), event.side, float(n_7), float(n_14), days_since, next_4d)
            )
            past.append(current)
            last_match = current
    result = pd.DataFrame(
        rows,
        columns=["id", "side", "matches_7d", "matches_14d", "days_since_match", "next_euro_4d"],
    )
    home = (
        result[result.side.eq("home")]
        .drop(columns="side")
        .add_prefix("home_")
        .rename(columns={"home_id": "id"})
    )
    away = (
        result[result.side.eq("away")]
        .drop(columns="side")
        .add_prefix("away_")
        .rename(columns={"away_id": "id"})
    )
    return home.merge(away, on="id", validate="one_to_one")


def build_comp_xg_features(source: pd.DataFrame) -> pd.DataFrame:
    """Считать предматчевую форму xG отдельно по команде и соревнованию."""
    common = source[["match_id", "datetime", "competition_code"]]
    home = common.assign(
        team_id=source.home_team_id,
        side="home",
        xg_diff=source.home_xg_all - source.away_xg_all,
    )
    away = common.assign(
        team_id=source.away_team_id,
        side="away",
        xg_diff=source.away_xg_all - source.home_xg_all,
    )
    participants = pd.concat([home, away], ignore_index=True).sort_values(
        ["team_id", "competition_code", "datetime", "match_id"]
    )
    participants["prior_xg"] = participants.groupby(
        ["team_id", "competition_code"], sort=False, dropna=False
    ).xg_diff.transform(
        lambda values: values.shift(1)
        .ewm(span=10, min_periods=3, adjust=False, ignore_na=True)
        .mean()
    )
    home_values = participants.loc[participants.side.eq("home"), ["match_id", "prior_xg"]].rename(
        columns={"match_id": "id", "prior_xg": COMP_XG_COLUMNS[0]}
    )
    away_values = participants.loc[participants.side.eq("away"), ["match_id", "prior_xg"]].rename(
        columns={"match_id": "id", "prior_xg": COMP_XG_COLUMNS[1]}
    )
    result = home_values.merge(away_values, on="id", validate="one_to_one")
    result[COMP_XG_COLUMNS[2]] = result[COMP_XG_COLUMNS[0]] - result[COMP_XG_COLUMNS[1]]
    return result


def score_predictions(
    frame: pd.DataFrame, probabilities: np.ndarray, *, fold: str, variant: str, n_features: int
) -> dict[str, Any]:
    """Оценить 1X2 и одну ставку по фиксированному правилу EPIC-041."""
    truth: Any = np.select(
        [
            frame.home_goals_all.to_numpy() > frame.away_goals_all.to_numpy(),
            frame.home_goals_all.to_numpy() < frame.away_goals_all.to_numpy(),
        ],
        [0, 2],
        default=1,
    )
    one_hot = cast(Any, np.eye(3))[truth]
    odds = frame[["odd_home", "odd_draw", "odd_away"]].to_numpy(dtype=float)
    valid: Any = cast(Any, np.isfinite(odds)).all(axis=1) & cast(Any, odds > 1).all(axis=1)
    selection: Any = np.full(len(frame), False)
    outcome: Any = np.full(len(frame), -1)
    if valid.any():
        edges = probabilities[valid] - 1.0 / odds[valid]
        choice = edges.argmax(axis=1)
        selection[valid] = edges[np.arange(len(choice)), choice] > 0.05
        outcome[valid] = choice
    bet_rows = np.flatnonzero(selection)
    chosen_odds = odds[bet_rows, outcome[bet_rows]]
    wins = truth[bet_rows] == outcome[bet_rows]
    returns = wins * chosen_odds - 1.0
    return {
        "fold": fold,
        "variant": variant,
        "n_events": len(frame),
        "n_features": n_features,
        "logloss": float(log_loss(truth, probabilities, labels=[0, 1, 2])),
        "brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "accuracy": float(np.mean(probabilities.argmax(axis=1) == truth)),
        "n_bets": int(len(bet_rows)),
        "coverage": float(len(bet_rows) / len(frame)),
        "roi": float(returns.mean()) if len(returns) else None,
        "profit_unit_stakes": float(returns.sum()),
        "selected_calibration_gap": float(
            np.mean(wins - probabilities[bet_rows, outcome[bet_rows]])
        )
        if len(bet_rows)
        else None,
        "odds_valid": int(valid.sum()),
    }


def main() -> None:
    """Выполнить одинаковые временные fold для фиксированных вариантов."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["baseline", "lean", "elo", "calendar", "lean_elo_calendar"],
        choices=["baseline", "lean", "elo", "elo_only", "calendar", "lean_elo_calendar", "comp_xg"],
    )
    args = parser.parse_args()
    source = load_source(args.source)
    feature_names = args.features.read_text(encoding="utf-8").splitlines()
    meta = [
        "id",
        "datetime",
        "competition_code",
        "home_goals_all",
        "away_goals_all",
        "odd_home",
        "odd_draw",
        "odd_away",
    ]
    frame = pd.read_parquet(args.processed, columns=meta + feature_names)
    frame["datetime"] = pd.to_datetime(frame.datetime, utc=True)
    frame = frame[frame.datetime.lt("2025-07-01")].copy()
    frame["id"] = frame.id.astype(str)
    elo = build_elo_features(source)
    calendar = build_calendar_features(source)
    comp_xg = build_comp_xg_features(source)
    elo["id"] = elo.id.astype(str)
    calendar["id"] = calendar.id.astype(str)
    comp_xg["id"] = comp_xg.id.astype(str)
    frame = frame.merge(elo, on="id", validate="one_to_one")
    frame = frame.merge(calendar, on="id", validate="one_to_one")
    frame = frame.merge(comp_xg, on="id", validate="one_to_one")
    if len(frame) != 28338:
        raise ValueError(f"Неожиданное число матчей до holdout: {len(frame)}")
    results: list[dict[str, Any]] = []
    traces: list[pd.DataFrame] = []
    variants = tuple(args.variants)
    for start_year, end_year in FOLDS:
        start, end = (
            pd.Timestamp(f"{start_year}-07-01", tz="UTC"),
            pd.Timestamp(f"{end_year}-07-01", tz="UTC"),
        )
        train = frame[frame.datetime.lt(start)]
        valid = frame[frame.datetime.ge(start) & frame.datetime.lt(end)]
        train_truth = np.select(
            [
                train.home_goals_all.to_numpy() > train.away_goals_all.to_numpy(),
                train.home_goals_all.to_numpy() < train.away_goals_all.to_numpy(),
            ],
            [0, 2],
            default=1,
        )
        print(f"fold {start_year}: train={len(train)}, valid={len(valid)}", flush=True)
        market_odds = valid[["odd_home", "odd_draw", "odd_away"]].to_numpy(float)
        market_valid: Any = cast(Any, np.isfinite(market_odds)).all(axis=1) & cast(
            Any, market_odds > 1
        ).all(axis=1)
        market_probs = 1.0 / market_odds[market_valid]
        market_probs /= market_probs.sum(axis=1, keepdims=True)
        market_result = score_predictions(
            cast(pd.DataFrame, valid.iloc[cast(Any, np.flatnonzero(market_valid))]),
            market_probs,
            fold=str(start_year),
            variant="market",
            n_features=0,
        )
        results.append(market_result)
        print(json.dumps(market_result, ensure_ascii=False), flush=True)
        lean_names = [
            name
            for name in feature_names
            if train[name].notna().mean() >= 0.5 and train[name].nunique(dropna=True) > 1
        ]
        for variant in variants:
            selected = list(lean_names if variant.startswith("lean") else feature_names)
            if variant == "elo_only":
                selected = list(ELO_COLUMNS)
            elif "elo" in variant:
                selected = [*selected, *ELO_COLUMNS]
            if "calendar" in variant:
                selected = [*selected, *CALENDAR_COLUMNS]
            if variant == "comp_xg":
                selected = [*selected, *COMP_XG_COLUMNS]
            model = CatBoostClassifier(
                loss_function="MultiClass",
                iterations=300,
                depth=4,
                learning_rate=0.0356058,
                l2_leaf_reg=13.0,
                rsm=1.0 if variant == "elo_only" else 0.2,
                random_seed=42,
                verbose=False,
                thread_count=4,
                allow_writing_files=False,
            )
            model.fit(train[selected], train_truth)
            probabilities = model.predict_proba(valid[selected])
            order = [list(model.classes_).index(value) for value in (0, 1, 2)]
            result = score_predictions(
                valid,
                probabilities[:, order],
                fold=str(start_year),
                variant=variant,
                n_features=len(selected),
            )
            results.append(result)
            if args.trace_output is not None:
                trace = valid[
                    ["id", "datetime", "competition_code", "odd_home", "odd_draw", "odd_away"]
                ].copy()
                trace["fold"] = str(start_year)
                trace["variant"] = variant
                trace["truth"] = np.select(
                    [
                        valid.home_goals_all.to_numpy() > valid.away_goals_all.to_numpy(),
                        valid.home_goals_all.to_numpy() < valid.away_goals_all.to_numpy(),
                    ],
                    [0, 2],
                    default=1,
                )
                trace[["p_home", "p_draw", "p_away"]] = probabilities[:, order]
                traces.append(trace)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.trace_output is not None:
        args.trace_output.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(traces, ignore_index=True).to_csv(args.trace_output, index=False)


if __name__ == "__main__":
    main()
