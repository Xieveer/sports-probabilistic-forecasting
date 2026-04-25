"""Тесты Parquet-store линий Pinnacle (:mod:`sports_forecast.data.providers.odds.store`)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from sports_forecast.data.providers.odds import store
from sports_forecast.data.providers.odds.store import (
    load_odds_store,
    max_game_date_in_store,
    save_odds_store,
    upsert_odds_store,
    upsert_odds_store_file,
)


def _sample_row(
    game_date: str = "2024-01-10",
    home: str = "A",
    away: str = "B",
    close_home: float = 1.5,
    fetched_at: str = "2024-01-10T00:00:00+00:00",
) -> dict[str, object]:
    return {
        "game_date": game_date,
        "home_team_norm": home,
        "away_team_norm": away,
        "pinnacle_home_open": 1.4,
        "pinnacle_away_open": 3.0,
        "pinnacle_draw_open": None,
        "pinnacle_home_close": close_home,
        "pinnacle_away_close": 2.8,
        "pinnacle_draw_close": None,
        "pinnacle_total_open": 5.5,
        "pinnacle_total_close": 5.0,
        "fetched_at": fetched_at,
    }


def test_load_save_roundtrip(tmp_path) -> None:
    path = tmp_path / "pinnacle_odds.parquet"
    df = pd.DataFrame([_sample_row()])
    save_odds_store(df, path)
    loaded = load_odds_store(path)
    assert list(loaded.columns) == list(store.ODDS_STORE_COLUMNS)
    assert len(loaded) == 1
    assert float(loaded["pinnacle_home_close"].iloc[0]) == 1.5
    assert str(loaded["game_date"].iloc[0]) in ("2024-01-10", "2024-01-10 00:00:00")


def test_upsert_dedup_newer_fetched_wins() -> None:
    key = _sample_row(
        close_home=1.0,
        fetched_at="2024-01-01T00:00:00+00:00",
    )
    newer = {**key, "pinnacle_home_close": 2.0, "fetched_at": "2024-01-15T00:00:00+00:00"}
    existing = pd.DataFrame([key])
    new = pd.DataFrame([newer])
    out = upsert_odds_store(existing, new)
    assert len(out) == 1
    assert float(out["pinnacle_home_close"].iloc[0]) == 2.0


def test_upsert_dedup_equal_fetched_last_row_wins() -> None:
    ts = "2024-01-10T00:00:00+00:00"
    old = _sample_row(close_home=1.0, fetched_at=ts)
    new_row = {**_sample_row(close_home=2.0, fetched_at=ts), "pinnacle_away_close": 9.0}
    out = upsert_odds_store(pd.DataFrame([old]), pd.DataFrame([new_row]))
    assert len(out) == 1
    assert float(out["pinnacle_home_close"].iloc[0]) == 2.0


def test_max_game_date_in_store() -> None:
    df = pd.DataFrame(
        [
            _sample_row(game_date="2024-01-05"),
            _sample_row(game_date="2024-02-10"),
        ]
    )
    assert max_game_date_in_store(df) == date(2024, 2, 10)
    assert max_game_date_in_store(pd.DataFrame()) is None


def test_load_missing_file_empty_schema(tmp_path) -> None:
    p = tmp_path / "none.parquet"
    df = load_odds_store(p)
    assert df.empty
    assert list(df.columns) == list(store.ODDS_STORE_COLUMNS)


def test_upsert_empty_new_returns_existing() -> None:
    existing = pd.DataFrame([_sample_row()])
    out = upsert_odds_store(existing, pd.DataFrame(columns=list(store.ODDS_STORE_COLUMNS)))
    assert len(out) == 1
    assert float(out["pinnacle_home_close"].iloc[0]) == 1.5


def test_upsert_empty_both() -> None:
    empty = pd.DataFrame(columns=list(store.ODDS_STORE_COLUMNS))
    out = upsert_odds_store(empty, empty)
    assert out.empty
    assert list(out.columns) == list(store.ODDS_STORE_COLUMNS)


def test_upsert_file_from_missing_store(tmp_path) -> None:
    p = tmp_path / "d" / "pinnacle_odds.parquet"
    new = pd.DataFrame([_sample_row(fetched_at="2024-01-10T00:00:00+00:00")])
    out = upsert_odds_store_file(new, p)
    assert len(out) == 1
    assert p.exists()
    same = load_odds_store(p)
    pd.testing.assert_frame_equal(
        out.reset_index(drop=True),
        same.reset_index(drop=True),
        check_dtype=False,
    )


def test_upsert_file_merges_with_disk(tmp_path) -> None:
    p = tmp_path / "pinnacle_odds.parquet"
    first = pd.DataFrame([_sample_row(fetched_at="2024-01-01T00:00:00+00:00")])
    save_odds_store(first, p)
    second = pd.DataFrame(
        [
            {
                **_sample_row(fetched_at="2024-01-20T00:00:00+00:00"),
                "pinnacle_home_close": 3.3,
            }
        ]
    )
    out = upsert_odds_store_file(second, p)
    assert len(out) == 1
    assert float(out["pinnacle_home_close"].iloc[0]) == 3.3


def test_new_df_missing_fetched_at_filled_utc() -> None:
    row = _sample_row()
    del row["fetched_at"]
    new = pd.DataFrame([row])
    out = upsert_odds_store(pd.DataFrame(), new)
    assert len(out) == 1
    at = out["fetched_at"].iloc[0]
    assert at is not None
    s = str(at)
    assert "T" in s or s.endswith("Z") or "+" in s


def test_upsert_new_partial_nan_fetched_at() -> None:
    row = _sample_row()
    row2 = {**_sample_row(close_home=9.0), "fetched_at": pd.NA}
    new = pd.DataFrame([row, row2])
    out = upsert_odds_store(pd.DataFrame(), new)
    # одна тройка ключей; вторая строка с NA → current UTC, свежее эталонной 2024 → она остаётся
    assert len(out) == 1
    assert float(out["pinnacle_home_close"].iloc[0]) == 9.0
