"""Тесты StreakFeatureGenerator (R27)."""

from __future__ import annotations

import time

import pandas as pd

from sports_forecast.features.generators.streak_generator import StreakFeatureGenerator


def test_streak_pre_match_state_and_win_rate() -> None:
    rows = [
        {
            "id": 1,
            "datetime": "2024-01-01",
            "side": "h",
            "pl": "H",
            "opp": "A",
            "pl_points": 3.0,
            "opp_points": 1.0,
        },
        {
            "id": 1,
            "datetime": "2024-01-01",
            "side": "a",
            "pl": "A",
            "opp": "H",
            "pl_points": 1.0,
            "opp_points": 3.0,
        },
        {
            "id": 2,
            "datetime": "2024-01-02",
            "side": "h",
            "pl": "H",
            "opp": "B",
            "pl_points": 2.0,
            "opp_points": 4.0,
        },
        {
            "id": 2,
            "datetime": "2024-01-02",
            "side": "a",
            "pl": "B",
            "opp": "H",
            "pl_points": 4.0,
            "opp_points": 2.0,
        },
        {
            "id": 3,
            "datetime": "2024-01-03",
            "side": "h",
            "pl": "H",
            "opp": "C",
            "pl_points": 5.0,
            "opp_points": 0.0,
        },
        {
            "id": 3,
            "datetime": "2024-01-03",
            "side": "a",
            "pl": "C",
            "opp": "H",
            "pl_points": 0.0,
            "opp_points": 5.0,
        },
    ]
    df = pd.DataFrame(rows)
    gen = StreakFeatureGenerator(
        {"type": "streak", "enabled": True, "win_mode": "points", "win_rate_windows": [3]}
    )
    out = gen.generate(df)

    h_m2 = out[(out["id"] == 2) & (out["side"] == "h")].iloc[0]
    assert float(h_m2["pl_win_streak"]) == 1.0
    assert float(h_m2["opp_win_streak"]) == 0.0

    h_m3 = out[(out["id"] == 3) & (out["side"] == "h")].iloc[0]
    assert float(h_m3["pl_win_streak"]) == 0.0
    assert float(h_m3["pl_lose_streak"]) == 1.0


def test_streak_goals_full_fallback_columns() -> None:
    rows = [
        {
            "id": 1,
            "datetime": "2024-01-01",
            "side": "h",
            "pl": "X",
            "opp": "Y",
            "pl_points": 2.0,
            "opp_points": 1.0,
        },
        {
            "id": 1,
            "datetime": "2024-01-01",
            "side": "a",
            "pl": "Y",
            "opp": "X",
            "pl_points": 1.0,
            "opp_points": 2.0,
        },
    ]
    df = pd.DataFrame(rows)
    gen = StreakFeatureGenerator(
        {"type": "streak", "win_mode": "goals_full", "win_rate_windows": [5]}
    )
    out = gen.generate(df)
    assert float(out.loc[out["side"] == "h", "pl_win_streak"].iloc[0]) == 0.0


def test_streak_many_matches_completes_quickly() -> None:
    """Регрессия O(n²): поиск away по id не должен сканировать весь long на каждый матч."""
    n_m = 4000
    base = pd.Timestamp("2020-01-01", tz="UTC")
    rows: list[dict[str, object]] = []
    for m in range(n_m):
        tid = m + 1
        ts = base + pd.Timedelta(days=m)
        rows.append(
            {
                "id": tid,
                "datetime": ts,
                "side": "h",
                "pl": f"H{m % 20}",
                "opp": f"A{m % 20}",
                "pl_points": 2.0,
                "opp_points": 1.0,
            }
        )
        rows.append(
            {
                "id": tid,
                "datetime": ts,
                "side": "a",
                "pl": f"A{m % 20}",
                "opp": f"H{m % 20}",
                "pl_points": 1.0,
                "opp_points": 2.0,
            }
        )
    df = pd.DataFrame(rows)
    gen = StreakFeatureGenerator(
        {"type": "streak", "enabled": True, "win_mode": "points", "win_rate_windows": [5]}
    )
    t0 = time.perf_counter()
    out = gen.generate(df)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"streak too slow: {elapsed:.2f}s for {len(df)} rows"
    assert len(out) == 2 * n_m
    assert out["pl_win_streak"].notna().all()
