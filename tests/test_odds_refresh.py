"""Тесты инкрементального odds-refresh: окна дат, cap, ``refresh_state``."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds import refresh as refresh_mod
from sports_forecast.data.providers.odds import store as store_mod
from sports_forecast.data.providers.odds.refresh import (
    RefreshState,
    build_incremental_need_range,
    build_refresh_segment,
    default_refresh_state_path,
    load_refresh_state,
    run_odds_refresh,
    save_refresh_state,
)
from sports_forecast.data.providers.odds.store import ODDS_STORE_COLUMNS


def _book_root_nhl() -> dict:
    return {
        "bookmakers": {"primary": "pinnacle"},
        "seasons": {
            "nhl": [
                {
                    "name": "t",
                    "date_from": "2025-10-01",
                    "date_to": "2026-06-30",
                }
            ]
        },
    }


def _row(**kwargs: object) -> dict:
    base = dict.fromkeys(ODDS_STORE_COLUMNS)
    base.update(
        {
            "game_date": "2025-12-20",
            "home_team_norm": "a",
            "away_team_norm": "b",
            "fetched_at": "2025-12-20T00:00:00+00:00",
        }
    )
    base.update(kwargs)
    return base


def test_empty_store_uses_season_from_config() -> None:
    br = OmegaConf.create(_book_root_nhl())
    plan = build_incremental_need_range(pd.DataFrame(), 3, date(2025, 12, 15), br, "nhl", None)
    assert plan.used_empty_store_season
    assert plan.need_from == date(2025, 10, 1)
    assert plan.need_to == date(2025, 12, 15)


def test_nonempty_store_bumps_from_max_minus_buffer() -> None:
    br = OmegaConf.create(_book_root_nhl())
    df = pd.DataFrame([_row(game_date="2025-12-20")])
    plan = build_incremental_need_range(df, 3, date(2025, 12, 25), br, "nhl", None)
    assert not plan.used_empty_store_season
    assert plan.need_to == date(2025, 12, 25)
    assert plan.need_from == date(2025, 12, 20) - timedelta(days=3)


def test_checkpoint_merges_last_successful_buffer() -> None:
    br = OmegaConf.create(_book_root_nhl())
    df = pd.DataFrame([_row(game_date="2025-12-20")])
    st = RefreshState(
        last_successful_date="2025-12-10",
        in_progress_from=None,
        updated_at="x",
    )
    plan = build_incremental_need_range(df, 3, date(2025, 12, 25), br, "nhl", st)
    assert plan.need_from == min(
        date(2025, 12, 20) - timedelta(days=3),
        date(2025, 12, 10) - timedelta(days=3),
    )


def test_max_days_per_refresh_clips() -> None:
    plan_ok = refresh_mod.RefreshDatePlan(
        need_from=date(2025, 1, 1), need_to=date(2025, 1, 31), used_empty_store_season=False
    )
    seg = build_refresh_segment(plan_ok, max_days_per_refresh=10, state=None)
    assert seg.date_from == date(2025, 1, 1)
    assert seg.date_to == date(2025, 1, 10)
    assert seg.has_more
    st = RefreshState(last_successful_date=None, in_progress_from="2025-01-11", updated_at="x")
    seg2 = build_refresh_segment(plan_ok, 10, st)
    assert seg2.date_from == date(2025, 1, 11)


def test_state_resume_in_progress() -> None:
    plan = refresh_mod.RefreshDatePlan(
        need_from=date(2025, 1, 1), need_to=date(2025, 1, 31), used_empty_store_season=False
    )
    st = RefreshState(
        last_successful_date="2025-01-10",
        in_progress_from="2025-01-11",
        updated_at="x",
    )
    seg = build_refresh_segment(plan, 10, st)
    assert seg.date_from == date(2025, 1, 11)


def test_save_load_refresh_state_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "refresh_state.json"
    st = RefreshState(
        last_successful_date="2025-01-10",
        in_progress_from="2025-01-20",
        updated_at="2025-01-10T00:00:00+00:00",
    )
    save_refresh_state(p, st)
    loaded = load_refresh_state(p)
    assert loaded is not None
    assert loaded.last_successful_date == "2025-01-10"
    assert loaded.in_progress_from == "2025-01-20"


def test_run_odds_refresh_mocked_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st_path = tmp_path / "s" / "odds" / "refresh_state.json"
    sp = tmp_path / "s" / "odds" / "pinnacle_odds.parquet"
    _df = pd.DataFrame([_row()])
    store_mod.save_odds_store(_df, sp)

    def _bf(**kwargs) -> pd.DataFrame:  # noqa: ANN003
        assert kwargs["date_from"] == date(2025, 12, 17)
        assert kwargs["date_to"] == date(2025, 12, 25)
        return pd.DataFrame([_row(game_date="2025-12-25")])

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.refresh.load_bookmaker_config",
        lambda k: _fake_book_cfg(),
    )
    r = run_odds_refresh(
        tournament="nhl",
        store_path=sp,
        refresh_state_path=st_path,
        project_root=tmp_path,
        source_config_name=None,
        today=date(2025, 12, 25),
        run_backfill_fn=_bf,
        buffer_days=3,
        max_days_per_refresh=30,
        auto_merge=False,
    )
    assert r.new_odds_rows == 1
    final = load_refresh_state(st_path)
    assert final is not None
    assert final.in_progress_from is None
    assert final.last_successful_date == "2025-12-25"


def _fake_book_cfg() -> object:
    return OmegaConf.create(
        {
            "bookmaker": {
                "name": "the_odds_api",
                "seasons": {
                    "nhl": [
                        {
                            "name": "t",
                            "date_from": "2025-10-01",
                            "date_to": "2026-06-30",
                        }
                    ]
                },
            }
        }
    )


def test_default_refresh_state_path() -> None:
    p = default_refresh_state_path("nhl", Path("/p"))
    assert p == Path("/p/data/source/nhl/odds/refresh_state.json")
