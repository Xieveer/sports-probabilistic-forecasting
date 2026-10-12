"""Контракт source-снимка будущих клубных матчей Smart Tables."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sports_forecast.data.club_upcoming import normalize_match_center_upcoming
from sports_forecast.data.providers.smart_tables.catalog import CompetitionEntry


def _competition() -> CompetitionEntry:
    return CompetitionEntry(
        country_slug="england",
        competition_slug="premier_league",
        competition_id=13,
        code="ENG1",
        title="Premier League",
        for_national_teams=0,
        match_count=1000,
    )


def test_match_center_id_is_namespaced_and_scores_remain_missing() -> None:
    observed_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "data": {
            "item": {
                "id": 576496,
                "competition_id": 13,
                "season_id": 24,
                "status": "not-started",
                "begin_at": (observed_at + timedelta(days=2)).isoformat(),
                "home_goals": None,
                "away_goals": None,
            },
            "teams": {
                "home": {"id": 1, "common_title": "Home", "is_national": 0},
                "away": {"id": 2, "common_title": "Away", "is_national": 0},
            },
        }
    }
    row = normalize_match_center_upcoming(payload, _competition(), observed_at, requested_id=576496)
    assert row is not None
    assert row["match_id"] == "mc:576496"
    assert row["competition_code"] == "ENG1"
    assert row["home_team_name"] == "Home"
    assert row["away_team_name"] == "Away"
    assert row["match_is_end"] == 0
    assert row["datetime"] == (observed_at + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    assert row["home_score_ft"] is None
    assert row["away_score_ft"] is None
    payload["data"]["item"]["competition_id"] = 14
    assert (
        normalize_match_center_upcoming(payload, _competition(), observed_at, requested_id=576496)
        is None
    )


def test_match_center_rejects_mismatched_id_and_incomplete_teams() -> None:
    observed_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "data": {
            "item": {
                "id": 576496,
                "competition_id": 13,
                "status": "not-started",
                "begin_at": (observed_at + timedelta(days=2)).isoformat(),
                "home_goals": None,
                "away_goals": None,
            },
            "teams": {
                "home": {"id": 1, "common_title": "Home"},
                "away": {"id": 2, "common_title": "Away"},
            },
        }
    }
    assert (
        normalize_match_center_upcoming(payload, _competition(), observed_at, requested_id=42)
        is None
    )
    payload["data"]["teams"]["home"].pop("id")
    assert (
        normalize_match_center_upcoming(payload, _competition(), observed_at, requested_id=576496)
        is None
    )
    payload["data"]["teams"]["home"]["id"] = 1
    payload["data"]["teams"]["away"]["common_title"] = ""
    assert (
        normalize_match_center_upcoming(payload, _competition(), observed_at, requested_id=576496)
        is None
    )
