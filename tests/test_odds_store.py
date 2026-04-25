"""Тесты Parquet-store линий (:mod:`sports_forecast.data.providers.odds.store`), V3 + миграция V1/V2."""

from __future__ import annotations

from datetime import date

import pandas as pd

from sports_forecast.data.providers.odds import store
from sports_forecast.data.providers.odds.store import (
    ODDS_STORE_COLUMNS_V1,
    ODDS_STORE_COLUMNS_V2,
    ODDS_STORE_COLUMNS_V3,
    load_odds_store,
    max_game_date_in_store,
    migrate_v1_to_v2,
    migrate_v1_to_v3,
    migrate_v2_to_v3,
    save_odds_store,
    upsert_odds_store,
    upsert_odds_store_file,
)


def _sample_row_v1(
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


def _sample_row_v2(
    game_date: str = "2024-01-10",
    home: str = "A",
    away: str = "B",
    commence: str = "2024-01-10T20:00:00+00:00",
    close_home: float = 1.5,
    fetched_at: str = "2024-01-10T00:00:00+00:00",
) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(ODDS_STORE_COLUMNS_V2, None)
    row.update(
        {
            "game_date": game_date,
            "home_team_norm": home,
            "away_team_norm": away,
            "commence_time_utc": commence,
            "pinnacle_winner_withOT_home_open": 1.4,
            "pinnacle_winner_withOT_away_open": 3.0,
            "pinnacle_winner_withOT_home_close": close_home,
            "pinnacle_winner_withOT_away_close": 2.8,
            "pinnacle_total_withOT_over_open": 5.5,
            "pinnacle_total_withOT_over_close": 5.0,
            "fetched_at": fetched_at,
        }
    )
    return row


def _sample_row_v3(
    game_date: str = "2024-01-10",
    home: str = "A",
    away: str = "B",
    commence: str = "2024-01-10T20:00:00+00:00",
    close_home: float = 1.5,
    fetched_at: str = "2024-01-10T00:00:00+00:00",
) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(ODDS_STORE_COLUMNS_V3, None)
    row.update(
        {
            "game_date": game_date,
            "home_team_norm": home,
            "away_team_norm": away,
            "commence_time_utc": commence,
            "close_snapshot_utc": "2024-01-10T19:00:00+00:00",
            "close_minutes_before": 60.0,
            "pinnacle_winner_withOT_home_close": close_home,
            "pinnacle_winner_withOT_away_close": 2.8,
            "fetched_at": fetched_at,
        }
    )
    return row


def test_migrate_v1_to_v2_maps_pinnacle_columns() -> None:
    v1 = pd.DataFrame([_sample_row_v1()])
    v2 = migrate_v1_to_v2(v1)
    assert list(v2.columns) == list(ODDS_STORE_COLUMNS_V2)
    assert float(v2["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5
    assert float(v2["pinnacle_total_withOT_over_open"].iloc[0]) == 5.5
    assert float(v2["pinnacle_total_withOT_over_close"].iloc[0]) == 5.0
    assert pd.isna(v2["commence_time_utc"].iloc[0])
    assert pd.isna(v2["onexbet_winner_home_open"].iloc[0])


def test_migrate_v1_empty_yields_v2_schema() -> None:
    empty = pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V1))
    out = migrate_v1_to_v2(empty)
    assert out.empty
    assert list(out.columns) == list(ODDS_STORE_COLUMNS_V2)


def test_load_autodetects_v1_parquet_and_migrates(tmp_path) -> None:
    path = tmp_path / "legacy.parquet"
    pd.DataFrame([_sample_row_v1()]).to_parquet(path, index=False)
    loaded = load_odds_store(path)
    assert list(loaded.columns) == list(store.ODDS_STORE_COLUMNS)
    assert "open_snapshot_utc" not in loaded.columns
    assert float(loaded["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5


def test_load_v2_parquet_migrates_to_v3(tmp_path) -> None:
    path = tmp_path / "v2.parquet"
    pd.DataFrame([_sample_row_v2()]).to_parquet(path, index=False)
    loaded = load_odds_store(path)
    assert list(loaded.columns) == list(ODDS_STORE_COLUMNS_V3)
    assert "pinnacle_winner_withOT_home_open" not in loaded.columns
    assert loaded["commence_time_utc"].iloc[0] == "2024-01-10T20:00:00+00:00"


def test_load_save_roundtrip_v3_from_v2_input(tmp_path) -> None:
    path = tmp_path / "pinnacle_odds.parquet"
    df = pd.DataFrame([_sample_row_v2()])
    save_odds_store(df, path)
    loaded = load_odds_store(path)
    assert list(loaded.columns) == list(store.ODDS_STORE_COLUMNS)
    assert len(loaded) == 1
    assert float(loaded["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5
    assert str(loaded["game_date"].iloc[0]) in ("2024-01-10", "2024-01-10 00:00:00")


def test_save_accepts_v1_input_writes_v3(tmp_path) -> None:
    path = tmp_path / "out.parquet"
    save_odds_store(pd.DataFrame([_sample_row_v1()]), path)
    loaded = pd.read_parquet(path)
    assert "commence_time_utc" in loaded.columns
    assert "pinnacle_home_close" not in loaded.columns
    assert float(loaded["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5


def test_upsert_dedup_newer_fetched_wins() -> None:
    key = _sample_row_v3(
        close_home=1.0,
        fetched_at="2024-01-01T00:00:00+00:00",
    )
    newer = {
        **key,
        "pinnacle_winner_withOT_home_close": 2.0,
        "fetched_at": "2024-01-15T00:00:00+00:00",
    }
    existing = pd.DataFrame([key])
    new = pd.DataFrame([newer])
    out = upsert_odds_store(existing, new)
    assert len(out) == 1
    assert list(out.columns) == list(ODDS_STORE_COLUMNS_V3)
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 2.0


def test_upsert_new_v1_merged_with_existing() -> None:
    existing = pd.DataFrame([_sample_row_v3(close_home=1.1)])
    new_v1 = pd.DataFrame([_sample_row_v1(close_home=2.2, fetched_at="2025-01-01T00:00:00+00:00")])
    out = upsert_odds_store(existing, new_v1)
    assert len(out) == 1
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 2.2


def test_upsert_dedup_equal_fetched_last_row_wins() -> None:
    ts = "2024-01-10T00:00:00+00:00"
    old = _sample_row_v3(close_home=1.0, fetched_at=ts)
    new_row = {
        **_sample_row_v3(close_home=2.0, fetched_at=ts),
        "pinnacle_winner_withOT_away_close": 9.0,
    }
    out = upsert_odds_store(pd.DataFrame([old]), pd.DataFrame([new_row]))
    assert len(out) == 1
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 2.0


def test_max_game_date_in_store() -> None:
    df = pd.DataFrame(
        [
            _sample_row_v3(game_date="2024-01-05"),
            _sample_row_v3(game_date="2024-02-10"),
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
    existing = pd.DataFrame([_sample_row_v3()])
    out = upsert_odds_store(existing, pd.DataFrame(columns=list(store.ODDS_STORE_COLUMNS)))
    assert len(out) == 1
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5


def test_upsert_empty_both() -> None:
    empty = pd.DataFrame(columns=list(store.ODDS_STORE_COLUMNS))
    out = upsert_odds_store(empty, empty)
    assert out.empty
    assert list(out.columns) == list(store.ODDS_STORE_COLUMNS)


def test_upsert_file_from_missing_store_v3(tmp_path) -> None:
    p = tmp_path / "d" / "pinnacle_odds.parquet"
    new = pd.DataFrame([_sample_row_v3(fetched_at="2024-01-10T00:00:00+00:00")])
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
    first = pd.DataFrame([_sample_row_v3(fetched_at="2024-01-01T00:00:00+00:00")])
    save_odds_store(first, p)
    second = pd.DataFrame(
        [
            {
                **_sample_row_v3(fetched_at="2024-01-20T00:00:00+00:00"),
                "pinnacle_winner_withOT_home_close": 3.3,
            }
        ]
    )
    out = upsert_odds_store_file(second, p)
    assert len(out) == 1
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 3.3


def test_new_df_missing_fetched_at_filled_utc() -> None:
    row = _sample_row_v3()
    del row["fetched_at"]
    new = pd.DataFrame([row])
    out = upsert_odds_store(pd.DataFrame(), new)
    assert len(out) == 1
    at = out["fetched_at"].iloc[0]
    assert at is not None
    s = str(at)
    assert "T" in s or s.endswith("Z") or "+" in s


def test_upsert_new_partial_nan_fetched_at() -> None:
    row = _sample_row_v3()
    row2 = {**_sample_row_v3(close_home=9.0), "fetched_at": pd.NA}
    new = pd.DataFrame([row, row2])
    out = upsert_odds_store(pd.DataFrame(), new)
    assert len(out) == 1
    assert float(out["pinnacle_winner_withOT_home_close"].iloc[0]) == 9.0


def test_migrate_v1_drops_extra_columns() -> None:
    """V1-кадр с лишними полями: после миграции только схема V2 (edge case)."""
    r = {**_sample_row_v1(), "unused_legacy": 123}
    v2 = migrate_v1_to_v2(pd.DataFrame([r]))
    assert "unused_legacy" not in v2.columns
    assert list(v2.columns) == list(ODDS_STORE_COLUMNS_V2)


def test_migrate_v1_none_frame_yields_empty_v2() -> None:
    v2 = migrate_v1_to_v2(None)  # type: ignore[arg-type]
    assert v2.empty
    assert list(v2.columns) == list(ODDS_STORE_COLUMNS_V2)


def test_migrate_v2_to_v3_drops_open_and_draw_pinnacle() -> None:
    v2 = pd.DataFrame([_sample_row_v2()])
    v3 = migrate_v2_to_v3(v2)
    assert "open_snapshot_utc" not in v3.columns
    assert "pinnacle_winner_withOT_draw_close" not in v3.columns
    assert "pinnacle_winner_withOT_home_open" not in v3.columns
    assert list(v3.columns) == list(ODDS_STORE_COLUMNS_V3)
    assert float(v3["pinnacle_winner_withOT_home_close"].iloc[0]) == 1.5


def test_migrate_v1_to_v3_chain_matches_v1_to_v2_to_v3() -> None:
    v1 = pd.DataFrame([_sample_row_v1()])
    a = migrate_v1_to_v3(v1)
    b = migrate_v2_to_v3(migrate_v1_to_v2(v1))
    pd.testing.assert_frame_equal(
        a.reset_index(drop=True),
        b.reset_index(drop=True),
        check_dtype=False,
    )
    assert list(a.columns) == list(ODDS_STORE_COLUMNS_V3)


def test_roundtrip_v3_preserves_close_timings_and_totals(tmp_path) -> None:
    """Parquet save/load: close тайминги и line/over/under close для Pinnacle + onexbet."""
    row: dict = dict.fromkeys(ODDS_STORE_COLUMNS_V2, None)
    row.update(
        {
            "game_date": "2024-03-01",
            "home_team_norm": "H",
            "away_team_norm": "A",
            "commence_time_utc": "2024-03-01T18:00:00Z",
            "open_snapshot_utc": "2024-02-28T12:00:00Z",
            "close_snapshot_utc": "2024-03-01T17:00:00Z",
            "open_minutes_before": 3000.0,
            "close_minutes_before": 60.0,
            "pinnacle_total_withOT_line_open": 5.5,
            "pinnacle_total_withOT_over_open": 1.9,
            "pinnacle_total_withOT_under_open": 1.85,
            "pinnacle_total_withOT_line_close": 5.0,
            "pinnacle_total_withOT_over_close": 1.88,
            "pinnacle_total_withOT_under_close": 1.92,
            "onexbet_total_line_open": 4.0,
            "onexbet_total_over_open": 1.8,
            "onexbet_total_under_open": 1.9,
            "onexbet_total_line_close": 4.0,
            "onexbet_total_over_close": 1.8,
            "onexbet_total_under_close": 1.9,
            "fetched_at": "2024-03-01T00:00:00+00:00",
        }
    )
    path = tmp_path / "o.parquet"
    save_odds_store(pd.DataFrame([row]), path)
    got = load_odds_store(path)
    assert "open_snapshot_utc" not in got.columns
    assert str(got["close_snapshot_utc"].iloc[0]) == "2024-03-01T17:00:00Z"
    assert float(got["pinnacle_total_withOT_line_close"].iloc[0]) == 5.0
    assert float(got["onexbet_total_under_close"].iloc[0]) == 1.9
    assert float(got["close_minutes_before"].iloc[0]) == 60.0
