"""Юнит-тесты NHL roster JSON → фичи (без сети)."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sports_forecast.data.providers.nhl import roster as roster_mod
from sports_forecast.data.providers.nhl.roster import _compact_player
from sports_forecast.features.generators.roster_generator import (
    NhlRosterFeatureGenerator,
    _age_on_date,
    _roster_metrics,
)


def test_compact_player_backward_compatible_minimal() -> None:
    """Базовые ключи на месте; без опциональных полей в API — компактный объект."""
    p = {
        "playerId": 1,
        "firstName": {"default": "A"},
        "lastName": {"default": "B"},
        "positionCode": "C",
        "sweaterNumber": 12,
        "birthDate": "2000-06-01",
    }
    c = _compact_player(p)
    assert c["playerId"] == 1
    assert c["firstName"] == "A"
    assert c["lastName"] == "B"
    assert c["positionCode"] == "C"
    assert c["sweaterNumber"] == 12
    assert c["birthDate"] == "2000-06-01"
    assert "heightInCm" not in c
    assert "draft" not in c


def test_compact_player_optional_physical_and_draft() -> None:
    p = {
        "id": 2,
        "firstName": {"default": "X"},
        "lastName": {"default": "Y"},
        "position": "D",
        "sweaterNumber": 77,
        "birthDate": "1999-01-15",
        "heightInCm": 185,
        "weightInKg": 90,
        "shootsCatches": "L",
        "draftDetails": {"year": 2018, "round": 1, "overallPick": 17},
    }
    c = _compact_player(p)
    assert c["heightInCm"] == 185
    assert c["weightInKg"] == 90
    assert c["shootsCatches"] == "L"
    assert c["draft"] == {"year": 2018, "round": 1, "overallPick": 17}


def test_roster_metrics_goalie_order_and_single() -> None:
    ref = date(2025, 1, 1)
    blob = {
        "players": [
            {"positionCode": "G", "sweaterNumber": 40, "birthDate": "1995-01-01"},
            {"positionCode": "G", "sweaterNumber": 31, "birthDate": "1996-01-01"},
        ],
        "injured": [],
    }
    m = _roster_metrics(blob, ref, young_skaters_n=9)
    assert m["num_goalies"] == 2.0
    assert m["primary_goalie_sweater"] == 40.0
    assert m["single_goalie"] == 0.0


def test_roster_metrics_young_forwards_n2_mean_age_and_height() -> None:
    ref = date(2025, 1, 1)
    blob = {
        "players": [
            {
                "positionCode": "C",
                "birthDate": "2002-01-01",
                "heightInInches": 72,
            },
            {
                "positionCode": "L",
                "birthDate": "2000-01-01",
                "heightInInches": 70,
            },
            {
                "positionCode": "R",
                "birthDate": "1995-01-01",
                "heightInInches": 68,
            },
        ],
        "injured": [],
    }
    m = _roster_metrics(blob, ref, young_skaters_n=2)
    a1 = _age_on_date("2002-01-01", ref)
    a2 = _age_on_date("2000-01-01", ref)
    assert a1 is not None and a2 is not None
    assert m["young_forwards_mean_age"] == pytest.approx((a1 + a2) / 2, rel=1e-5)
    assert m["young_forwards_mean_height_in"] == pytest.approx((72 + 70) / 2, rel=1e-5)


def test_roster_metrics_injured_count() -> None:
    ref = date(2025, 1, 1)
    blob = {
        "players": [],
        "injured": [{"id": 1}, {"id": 2}],
    }
    m = _roster_metrics(blob, ref, young_skaters_n=3)
    assert m["injured_listed"] == 2.0


def test_nhl_roster_generator_inline_json() -> None:
    home = {
        "team": "AAA",
        "players": [
            {"positionCode": "C", "birthDate": "2001-01-01", "heightInCm": 178},
        ],
        "injured": ["x"],
    }
    away = {"team": "BBB", "players": [], "injured": []}
    df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2025-11-01T20:00:00Z")],
            "home_roster": [json.dumps(home, ensure_ascii=False)],
            "away_roster": [json.dumps(away, ensure_ascii=False)],
        }
    )
    gen = NhlRosterFeatureGenerator({"type": "nhl_roster", "young_skaters_n": 9, "enabled": True})
    out = gen.generate(df)
    assert out["home_num_forwards"].iloc[0] == 1.0
    assert out["away_roster_size"].iloc[0] == 0.0
    assert out["home_injured_listed"].iloc[0] == 1.0
    assert out["away_injured_listed"].iloc[0] == 0.0
    assert out["home_single_goalie"].iloc[0] == 0.0
    assert np.isnan(out["home_primary_goalie_sweater"].iloc[0])


def test_roster_to_json_cell_passes_injured_from_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeClient:
        def get_json(self, path: str) -> dict:  # noqa: ARG002
            return {
                "forwards": [],
                "defensemen": [],
                "goalies": [],
                "injured": [{"playerId": 99}],
            }

    def fake_fetch(_client: object, team: str, season: int) -> dict:
        calls.append({"team": team, "season": season})
        return {
            "forwards": [],
            "defensemen": [],
            "goalies": [],
            "injured": [{"playerId": 99}],
        }

    monkeypatch.setattr(roster_mod, "fetch_roster_payload", fake_fetch)
    cell = roster_mod.roster_to_json_cell(FakeClient(), "PIT", 20252026)  # type: ignore[arg-type]
    parsed = json.loads(cell)
    assert parsed["injured"] == [{"playerId": 99}]
    assert calls[0] == {"team": "PIT", "season": 20252026}
