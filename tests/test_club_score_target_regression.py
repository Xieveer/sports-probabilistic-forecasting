"""Допуск счёта для обеих стратегий клубного 1X2."""

import pandas as pd
import pytest
import yaml
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.config.model_strategy import effective_market_spec
from sports_forecast.utils.targets import TargetComputationError, compute_target_from_market_spec


@pytest.fixture(params=["football_long_binary", "football_wide_multiclass"])
def club_strategy(request):
    with initialize_config_dir(version_base="1.3", config_dir=str(PROJECT_ROOT / "conf")):
        cfg = compose(
            config_name="config",
            overrides=[
                "tournament=football_top_leagues",
                "market=winner",
                "market_spec=winner_1x2",
                "algorithm=catboost",
                "features=basic",
                f"model_strategy={request.param}",
            ],
        )
    return effective_market_spec(cfg), cfg.tournament


@pytest.mark.parametrize("invalid", [None, float("nan"), -1, 1.5, float("inf"), "нет"])
@pytest.mark.parametrize("column", [0, 1])
def test_both_strategies_reject_invalid_score(club_strategy, invalid, column) -> None:
    spec, tournament = club_strategy
    scores = [2, 1]
    scores[column] = invalid
    columns = (
        ["pl_points", "opp_points"]
        if spec.data_format == "long"
        else ["home_points", "away_points"]
    )
    frame = pd.DataFrame([dict(zip(columns, scores, strict=True))])
    with pytest.raises(TargetComputationError, match="полный неотрицательный целый счёт"):
        compute_target_from_market_spec(frame, spec, tournament)


def test_both_strategies_use_regulation_score(club_strategy) -> None:
    spec, tournament = club_strategy
    columns = (
        ["pl_points", "opp_points"]
        if spec.data_format == "long"
        else ["home_points", "away_points"]
    )
    frame = pd.DataFrame({columns[0]: ["2", "1", "0"], columns[1]: ["1", "1", "2"]})
    # Финальный счёт с дополнительным временем не влияет на 1X2.
    frame["home_goals_full"] = [2, 2, 0]
    frame["away_goals_full"] = [1, 1, 2]
    target = compute_target_from_market_spec(frame, spec, tournament)
    assert target.tolist() == ([1, 0, 0] if spec.data_format == "long" else [0, 1, 2])


def test_other_winner_market_keeps_existing_score_behavior() -> None:
    # Обычный winner другого вида спорта сохраняет прежнюю семантику.
    tournament = OmegaConf.create(
        {
            "target_sources": {
                "player_win": {
                    "format": "long",
                    "player_column": "pl_points",
                    "opponent_column": "opp_points",
                    "comparison": "greater",
                }
            }
        }
    )
    spec = OmegaConf.create(
        {"name": "winner", "data_format": "long", "target_source_key": "player_win"}
    )
    frame = pd.DataFrame({"pl_points": [None, -1, 1.5], "opp_points": [1, 0, 1]})
    assert compute_target_from_market_spec(frame, spec, tournament).tolist() == [0, 0, 1]


def test_ingest_tracks_club_score_audit_dependency() -> None:
    pipeline = yaml.safe_load((PROJECT_ROOT / "dvc.yaml").read_text(encoding="utf-8"))
    assert (
        "sports_forecast/validation/club_regulation_scores.py"
        in pipeline["stages"]["ingest"]["deps"]
    )
