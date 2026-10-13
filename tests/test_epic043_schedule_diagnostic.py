"""Проверка очков и календарного окна в исследовательской диагностике."""

from __future__ import annotations

import pandas as pd

from scripts.research.epic043_schedule_diagnostic import prepare_team_games


def test_draw_points_and_upcoming_euro_window() -> None:
    """Ничья даёт треть максимума, а еврокубок учитывается только позже матча."""
    source = pd.DataFrame(
        [
            {
                "match_id": 1,
                "datetime": "2024-09-01T12:00:00Z",
                "competition_code": "ENG1",
                "season_id": 2024,
                "home_team_id": 10,
                "away_team_id": 20,
                "home_goals_all": 1,
                "away_goals_all": 1,
                "odd_home": 2.0,
                "odd_draw": 4.0,
                "odd_away": 4.0,
            },
            {
                "match_id": 2,
                "datetime": "2024-09-04T12:00:00Z",
                "competition_code": "UCL",
                "season_id": 2024,
                "home_team_id": 10,
                "away_team_id": 30,
                "home_goals_all": 1,
                "away_goals_all": 0,
                "odd_home": 2.0,
                "odd_draw": 4.0,
                "odd_away": 4.0,
            },
        ]
    )
    games = prepare_team_games(source)
    home = games.loc[games.team_id.eq(10)].iloc[0]
    away = games.loc[games.team_id.eq(20)].iloc[0]
    assert home.before_euro
    assert not away.before_euro
    assert home.actual_points == 1 / 3
    assert home.market_points == 0.5 + 0.25 / 3
    assert away.market_points == 0.25 + 0.25 / 3
