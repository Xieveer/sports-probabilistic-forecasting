"""Тесты NHL schedule / standings пре-генераторов."""

from __future__ import annotations

from typing import cast

import pandas as pd

from sports_forecast.features.generators.schedule_generator import NhlScheduleFeatureGenerator
from sports_forecast.features.generators.standings_generator import NhlStandingsFeatureGenerator


def test_nhl_schedule_generator_basic() -> None:
    cfg = {
        "type": "nhl_schedule",
        "datetime_column": "datetime",
        "required_columns": ["home_team", "away_team", "datetime", "home_sog_ft"],
        "travel": {"enabled": False},
    }
    gen = NhlScheduleFeatureGenerator(cfg)
    df = pd.DataFrame(
        {
            "home_team": ["A", "A", "B"],
            "away_team": ["B", "C", "C"],
            "datetime": pd.to_datetime(
                [
                    "2024-01-01 19:00:00+00:00",
                    "2024-01-03 19:00:00+00:00",
                    "2024-01-02 19:00:00+00:00",
                ]
            ),
            "home_sog_ft": [30.0, 31.0, 29.0],
        }
    )
    out = gen.generate(df)
    assert "rest_advantage" in out.columns
    assert out["home_games_in_last_7d"].notna().all()
    assert "home_km_since_last_game" not in out.columns


def test_nhl_schedule_travel_features_coast_to_coast() -> None:
    """NYR (MSG) → LAK (Crypto): большой перелёт для гостей между играми."""
    cfg = {
        "type": "nhl_schedule",
        "datetime_column": "datetime",
        "required_columns": ["home_team", "away_team", "datetime", "home_sog_ft"],
        "travel": {"enabled": True},
    }
    gen = NhlScheduleFeatureGenerator(cfg)
    df = pd.DataFrame(
        {
            "home_team": ["NYR", "LAK"],
            "away_team": ["LAK", "NYR"],
            "datetime": pd.to_datetime(
                [
                    "2024-01-01 00:00:00+00:00",
                    "2024-01-05 03:00:00+00:00",
                ]
            ),
            "home_sog_ft": [28.0, 30.0],
        }
    )
    out = gen.generate(df)
    assert "home_km_since_last_game" in out.columns
    # Вторая строка: дома LAK, гости NYR; у NYR предыдущая площадка — NYR (играли в гостях у NYR дома MSG)
    raw_km = out.iloc[1]["away_km_since_last_game"]
    assert raw_km is not None and pd.notna(raw_km)
    assert cast(float, raw_km) > 3500.0
    raw_tz = out.iloc[1]["away_tz_shift_since_last"]
    assert raw_tz is not None and pd.notna(raw_tz)
    tz_away = cast(float, raw_tz)
    # Предыдущая площадка NYR — MSG (-5), текущая — Лос-Анджелес (-8)
    assert tz_away == -3.0


def test_nhl_standings_skips_without_columns() -> None:
    cfg = {"type": "nhl_standings"}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame({"home_team": ["A"], "away_team": ["B"], "datetime": [pd.Timestamp.utcnow()]})
    out = gen.generate(df)
    assert "conf_rank_diff" not in out.columns


def _standings_row(
    *,
    home_st: float,
    away_st: float,
    hp: float,
    ap: float,
    hgp: float = 40.0,
    agp: float = 40.0,
    hpts: float = 0.0,
    apts: float = 0.0,
    game_type: str | None = None,
    match_end: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "home_team": "H",
        "away_team": "A",
        "datetime": pd.Timestamp("2024-03-15 00:00:00+00:00"),
        "home_conference_standing": home_st,
        "away_conference_standing": away_st,
        "home_P": hp,
        "away_P": ap,
        "home_GP": hgp,
        "away_GP": agp,
        "home_points": hpts,
        "away_points": apts,
    }
    if game_type is not None:
        row["game_type"] = game_type
    if match_end is not None:
        row["match_end"] = match_end
    return row


def test_nhl_standings_motivation_playoff_line_and_points() -> None:
    """Ранг 8 — в зоне, 9 — на одно место ниже линии (8 слотов); очки/GP из таблицы."""
    cfg = {"type": "nhl_standings", "motivation": {"enabled": True, "playoff_line_slots": 8}}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame(
        [
            _standings_row(home_st=8.0, away_st=9.0, hp=90.0, ap=88.0, hgp=70.0, agp=71.0),
        ]
    )
    out = gen.generate(df)
    assert float(out.iloc[0]["home_playoff_spots_out"]) == 0.0
    assert float(out.iloc[0]["away_playoff_spots_out"]) == 1.0
    assert float(out.iloc[0]["playoff_spots_out_diff"]) == -1.0
    assert float(out.iloc[0]["standing_points_diff"]) == 2.0
    assert float(out.iloc[0]["gp_diff"]) == -1.0
    assert float(out.iloc[0]["standing_rank_gap"]) == 1.0
    assert "motivation_playoffs_phase" not in out.columns
    assert "motivation_extended_game" not in out.columns


def test_nhl_standings_motivation_game_type_and_match_end() -> None:
    cfg = {"type": "nhl_standings"}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame(
        [
            _standings_row(
                home_st=1.0,
                away_st=2.0,
                hp=100.0,
                ap=99.0,
                game_type="regular",
                match_end="REG",
            ),
            _standings_row(
                home_st=3.0,
                away_st=4.0,
                hp=98.0,
                ap=97.0,
                game_type="playoffs",
                match_end="OT",
            ),
        ]
    )
    out = gen.generate(df)
    assert float(out.iloc[0]["motivation_playoffs_phase"]) == 0.0
    assert float(out.iloc[0]["motivation_extended_game"]) == 0.0
    assert float(out.iloc[1]["motivation_playoffs_phase"]) == 1.0
    assert float(out.iloc[1]["motivation_extended_game"]) == 1.0


def test_nhl_standings_motivation_disabled() -> None:
    cfg = {"type": "nhl_standings", "motivation": {"enabled": False}}
    gen = NhlStandingsFeatureGenerator(cfg)
    df = pd.DataFrame(
        [
            _standings_row(
                home_st=9.0, away_st=8.0, hp=80.0, ap=82.0, game_type="regular", match_end=""
            ),
        ]
    )
    out = gen.generate(df)
    assert "standing_points_diff" not in out.columns
    assert "conf_rank_diff" in out.columns


def test_nhl_standings_motivation_expected_names_includes_optional() -> None:
    gen = NhlStandingsFeatureGenerator({"type": "nhl_standings"})
    exp = gen.get_expected_feature_names()
    assert "motivation_playoffs_phase" in exp
    df_no_opt = pd.DataFrame([_standings_row(home_st=1.0, away_st=2.0, hp=10.0, ap=9.0)])
    act = gen.get_actual_feature_names(df_no_opt)
    assert "motivation_playoffs_phase" not in act
