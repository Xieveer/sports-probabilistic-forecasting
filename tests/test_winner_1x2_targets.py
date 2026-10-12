"""Явный футбольный 1X2 target для одного рынка winner."""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.config.loaders import load_tournament_config
from sports_forecast.utils.targets import TargetComputationError, compute_target_from_market_spec


def _spec():
    return OmegaConf.create(
        {
            "name": "winner_1x2",
            "market_family": "winner",
            "data_format": "wide",
            "target_source_key": "home_result_1x2",
            "target_name": "target_result_1x2",
        }
    )


def test_winner_1x2_has_distinct_home_draw_away_classes() -> None:
    """Ничья получает собственный класс и не становится двумя поражениями."""
    frame = pd.DataFrame({"home_points": [2.0, 1.0, 0.0], "away_points": [0.0, 1.0, 3.0]})

    target = compute_target_from_market_spec(
        frame, _spec(), load_tournament_config("football_top_leagues")
    )

    assert target.tolist() == [0, 1, 2]


@pytest.mark.parametrize("home,away", [(None, 1.0), (2.0, None), (-1.0, 1.0)])
def test_winner_1x2_rejects_missing_or_negative_final_score(
    home: float | None, away: float | None
) -> None:
    """Неполный результат нельзя кодировать как поражение или ничью."""
    frame = pd.DataFrame({"home_points": [home], "away_points": [away]})

    with pytest.raises(TargetComputationError, match="счёт"):
        compute_target_from_market_spec(
            frame, _spec(), load_tournament_config("football_top_leagues")
        )
