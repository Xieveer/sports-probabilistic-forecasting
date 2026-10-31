"""Допуск счёта основного времени для клубного футбола Smart Tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_SCORE_COLUMNS = (
    "home_score_ft",
    "away_score_ft",
    "home_goals_all",
    "away_goals_all",
    "home_goals_1h",
    "away_goals_1h",
    "home_goals_2h",
    "away_goals_2h",
)
_REQUIRED_COLUMNS = frozenset(_SCORE_COLUMNS) | {
    "match_id",
    "competition_code",
    "match_status",
    "match_is_end",
}


def audit_regulation_scores(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Вернуть допущенные матчи и карантин с причиной по каждому match_id.

    `ft` трактуется как 90 минут только после сверки с `all` и суммой таймов.
    Отсутствие таймов или технический результат закрывают допуск.
    """
    missing = _REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Нет колонок контракта счёта: {sorted(missing)}")
    if frame["match_id"].isna().any() or frame["match_id"].duplicated().any():
        raise ValueError("match_id пустой или повторяется")
    score = frame.loc[:, _SCORE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    missing_period = (
        score[["home_goals_1h", "away_goals_1h", "home_goals_2h", "away_goals_2h"]]
        .isna()
        .any(axis=1)
    )
    invalid = (
        score.isna().any(axis=1) | score.lt(0).any(axis=1) | score.ne(score.round()).any(axis=1)
    )
    finished = frame["match_is_end"].astype(str).str.strip().isin({"1", "True", "true"})
    played = frame["match_status"].astype(str).str.strip().eq("Матч окончен")
    mismatch = pd.Series(False, index=frame.index)
    for side in ("home", "away"):
        mismatch |= score[f"{side}_score_ft"].ne(score[f"{side}_goals_all"])
        mismatch |= score[f"{side}_score_ft"].ne(
            score[f"{side}_goals_1h"] + score[f"{side}_goals_2h"]
        )
    reason = pd.Series("", index=frame.index, dtype="string")
    reason.loc[mismatch] = "score_mismatch"
    reason.loc[invalid] = "invalid_score"
    reason.loc[missing_period] = "missing_period_score"
    reason.loc[~(finished & played)] = "not_played"
    accepted = frame.loc[reason.eq("")].copy()
    rejected = frame.loc[reason.ne(""), ["match_id", "competition_code"]].copy()
    rejected["reason"] = reason.loc[reason.ne("")].to_numpy()
    return accepted, rejected


def main(argv: list[str] | None = None) -> int:
    """Проверить UCL/UEL snapshot и вывести агрегированный отчёт."""
    parser = argparse.ArgumentParser(description="Аудит счёта 90 минут UCL/UEL")
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data/source/football_top_leagues/source.csv",
    )
    args = parser.parse_args(argv)
    try:
        frame = pd.read_csv(args.source, low_memory=False)
        cups = frame.loc[frame["competition_code"].isin({"UCL", "UEL"})]
        accepted, rejected = audit_regulation_scores(cups)
    except (OSError, ValueError, KeyError) as exc:
        logger.error("Аудит счёта основного времени не прошёл: %s", exc)
        return 1
    report = {
        "cup_rows": len(cups),
        "accepted": len(accepted),
        "quarantined": len(rejected),
        "quarantine": rejected.to_dict(orient="records"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
