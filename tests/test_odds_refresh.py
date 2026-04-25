"""Тесты инкрементального odds-refresh: окна дат, cap, ``refresh_state``."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.data.providers.odds import refresh as refresh_mod
from sports_forecast.data.providers.odds import store as store_mod
from sports_forecast.data.providers.odds.backfill import BackfillRunResult
from sports_forecast.data.providers.odds.refresh import (
    RefreshState,
    _odds_runtime_from_source,
    build_incremental_need_range,
    build_refresh_segment,
    default_refresh_state_path,
    load_refresh_state,
    resolve_path_under_tournament_source,
    run_odds_refresh,
    save_refresh_state,
)
from sports_forecast.data.providers.odds.store import ODDS_STORE_COLUMNS
from sports_forecast.validation.schemas import validate_pinnacle_odds_float_columns


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


def test_resolve_path_under_tournament_source_relative_and_absolute() -> None:
    root = Path("/repo")
    rel = resolve_path_under_tournament_source(
        root, "nhl", "odds/custom.parquet", "odds/pinnacle_odds.parquet"
    )
    assert rel == root / "data" / "source" / "nhl" / "odds" / "custom.parquet"
    assert (
        resolve_path_under_tournament_source(root, "nhl", None, "odds/pinnacle_odds.parquet")
        == root / "data" / "source" / "nhl" / "odds" / "pinnacle_odds.parquet"
    )
    assert resolve_path_under_tournament_source(
        root, "nhl", "/var/o.parquet", "odds/pinnacle_odds.parquet"
    ) == Path("/var/o.parquet")


def test_odds_runtime_from_nhl_config_paths() -> None:
    _b, _m, _a, p_store, p_state, p_unm, min_cov = _odds_runtime_from_source(
        "nhl", "nhl", PROJECT_ROOT
    )
    assert p_store == PROJECT_ROOT / "data" / "source" / "nhl" / "odds" / "pinnacle_odds.parquet"
    assert p_state.name == "refresh_state.json"
    assert p_unm.name == "unmatched_teams.csv"
    assert min_cov == 70.0


def test_validate_pinnacle_odds_rejects_out_of_range() -> None:
    bad = pd.DataFrame([{"pinnacle_home_close": 1.0}])
    with pytest.raises(RuntimeError, match="unit"):
        validate_pinnacle_odds_float_columns(bad, context="unit")


def test_run_odds_refresh_backfill_result_quota_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    st_path = tmp_path / "s" / "odds" / "refresh_state.json"
    sp = tmp_path / "s" / "odds" / "pinnacle_odds.parquet"
    store_mod.save_odds_store(
        pd.DataFrame([_row()]),
        sp,
    )

    def _bf(**kwargs) -> BackfillRunResult:  # noqa: ANN003
        return BackfillRunResult(
            frame=pd.DataFrame([_row(game_date="2025-12-25")]),
            quota_hit=False,
            requests_remaining=42,
            requests_used=58,
        )

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
        auto_merge=False,
    )
    assert r.requests_remaining == 42
    assert r.requests_used == 58


def test_log_source_coverage_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from sports_forecast.data.providers.odds import refresh as refresh_mod

    caplog.set_level(logging.WARNING)
    src = tmp_path / "source.csv"
    # 3 строки: две с NaN в pinnacle_home_close, одна с коэф. → 33% < 50%
    src.write_text(
        "id,datetime,home_team,away_team,pinnacle_home_close\n"
        "a,2025-01-01T00:00:00+00:00,x,y,\n"
        "b,2025-01-02T00:00:00+00:00,x,y,\n"
        "c,2025-01-03T00:00:00+00:00,x,y,1.95\n",
        encoding="utf-8",
    )
    refresh_mod._log_source_odds_metrics(
        src,
        min_odds_coverage_pct=50.0,
        store_rows=1,
    )
    assert any("min_odds_coverage" in r.message for r in caplog.records)
