"""Проверки временной семантики исследовательских признаков EPIC-043."""

from typing import cast

import pandas as pd

from scripts.research.epic043_feature_experiments import (
    build_calendar_features,
    build_comp_xg_features,
    build_elo_features,
)


def test_elo_uses_only_prior_match_results() -> None:
    """Рейтинг текущего события не должен знать его результат."""
    events = pd.DataFrame(
        {
            "match_id": [1, 2],
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-04"], utc=True),
            "competition_code": ["ENG1", "ENG1"],
            "home_team_id": [10, 10],
            "away_team_id": [20, 30],
            "home_goals_all": [2, 0],
            "away_goals_all": [0, 1],
        }
    )
    ratings = build_elo_features(events).set_index("id")
    assert ratings.loc[1, "home_elo"] == 1500
    assert ratings.loc[1, "away_elo"] == 1500
    assert cast(float, ratings.loc[2, "home_elo"]) > 1500
    assert ratings.loc[2, "away_elo"] == 1500


def test_calendar_counts_past_and_marks_next_euro_fixture() -> None:
    """Будущий еврокубок отмечается, а будущий матч не входит в прошлую нагрузку."""
    events = pd.DataFrame(
        {
            "match_id": [1, 2, 3],
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-04", "2024-01-08"], utc=True),
            "competition_code": ["ENG1", "ENG1", "UCL"],
            "home_team_id": [10, 30, 10],
            "away_team_id": [20, 10, 40],
        }
    )
    calendar = build_calendar_features(events).set_index("id")
    assert calendar.loc[1, "home_matches_7d"] == 0
    assert calendar.loc[2, "away_matches_7d"] == 1
    assert calendar.loc[2, "away_days_since_match"] == 3
    assert calendar.loc[2, "away_next_euro_4d"] == 1
    assert calendar.loc[1, "home_next_euro_4d"] == 0
    assert calendar.loc[3, "home_matches_7d"] == 2


def test_competition_xg_excludes_current_match() -> None:
    """Контекст турнира созревает после трёх предыдущих наблюдений."""
    events = pd.DataFrame(
        {
            "match_id": [1, 2, 3, 4],
            "datetime": pd.to_datetime(
                ["2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22"], utc=True
            ),
            "competition_code": ["ENG1"] * 4,
            "home_team_id": [10] * 4,
            "away_team_id": [20, 30, 40, 50],
            "home_xg_all": [2.0, 2.0, 2.0, 100.0],
            "away_xg_all": [1.0] * 4,
        }
    )
    features = build_comp_xg_features(events).set_index("id")
    assert pd.isna(features.loc[3, "home_comp_xg_diff_ewm10"])
    assert features.loc[4, "home_comp_xg_diff_ewm10"] == 1.0
