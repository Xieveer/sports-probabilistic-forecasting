"""Тесты CLI/логики backfill The Odds API (сезоны, store, квота)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds import backfill as backfill_mod
from sports_forecast.data.providers.odds.backfill import (
    backfill_day_frames,
    default_odds_store_path,
    last_n_season_windows,
    main,
    run_backfill,
)
from sports_forecast.data.providers.odds.client import (
    OddsApiClient,
    OddsApiQuotaSnapshot,
    QuotaBudgetError,
)
from sports_forecast.data.providers.odds.snapshot_discovery import SnapshotPlan


def _minimal_bookmaker_node(
    *,
    seasons_nhl: list[dict[str, str]],
    quota: int = 1000,
) -> dict:
    return {
        "bookmakers": {"primary": "pinnacle"},
        "output_columns": {
            "moneyline": {
                "home_open": "pinnacle_home_open",
                "away_open": "pinnacle_away_open",
                "draw_open": "pinnacle_draw_open",
                "home_close": "pinnacle_home_close",
                "away_close": "pinnacle_away_close",
                "draw_close": "pinnacle_draw_close",
            },
            "total": {"open": "pinnacle_total_open", "close": "pinnacle_total_close"},
        },
        "backfill": {"open_snapshot_utc": "12:00:00", "close_snapshot_utc": "23:30:00"},
        "api": {
            "base_url": "https://api.the-odds-api.com",
            "api_prefix": "/v4",
            "markets_h2h": ["h2h"],
            "markets_totals": ["totals"],
        },
        "seasons": {"nhl": seasons_nhl},
        "quota_budget_per_run": quota,
    }


def test_last_n_season_windows_from_project_config() -> None:
    from sports_forecast.config.loaders import load_bookmaker_config

    cfg = load_bookmaker_config("the_odds_api")
    assert cfg is not None
    br = cfg.bookmaker
    w = last_n_season_windows(br, "nhl", 2)
    assert len(w) == 2
    assert w[0][0] == "2024-25"
    assert w[-1][0] == "2025-26"


def test_default_odds_store_path() -> None:
    p = default_odds_store_path("nhl", Path("/tmp/proj"))
    assert p == Path("/tmp/proj/data/source/nhl/odds/pinnacle_odds.parquet")


def test_main_rejects_seasons_with_from_to(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "x")
    rc = main(["--seasons", "2", "--from", "2024-01-01", "--to", "2024-01-02"])
    assert rc == 1


def test_main_requires_range_or_seasons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "x")
    rc = main(["--sport-key", "icehockey_nhl"])
    assert rc == 1


def test_main_passes_explicit_store_path_to_run_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "x")
    want = tmp_path / "custom" / "odds.parquet"
    captured: dict[str, Path | None] = {}

    def _rb(*, store_path, **kwargs):  # noqa: ANN003
        captured["store_path"] = store_path

    monkeypatch.setattr(backfill_mod, "run_backfill", _rb)
    rc = main(
        [
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-01",
            "--store",
            str(want),
        ]
    )
    assert rc == 0
    assert captured["store_path"] == want.resolve()


def test_run_backfill_seasons_and_store_upsert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    cfg = OmegaConf.create(
        {
            "bookmaker": _minimal_bookmaker_node(
                seasons_nhl=[
                    {
                        "name": "mini",
                        "date_from": "2024-01-01",
                        "date_to": "2024-01-01",
                    }
                ],
            )
        }
    )
    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.load_bookmaker_config",
        lambda _k: cfg,
    )

    class FakeClient:
        def fetch_odds_for_sport(self, *a, **k):  # noqa: ANN002, ANN003
            return {"data": []}

        def last_quota(self) -> OddsApiQuotaSnapshot:
            return OddsApiQuotaSnapshot(requests_remaining=None, requests_used=None)

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.OddsApiClient",
        lambda *a, **k: FakeClient(),
    )

    recorded: list[tuple[int, Path]] = []

    def _upsert(df, path: Path):  # noqa: ANN001
        recorded.append((len(df), path))
        return df

    monkeypatch.setattr(backfill_mod, "upsert_odds_store_file", _upsert)

    store = tmp_path / "p.parquet"
    run_backfill(
        seasons_last_n=1,
        tournament="nhl",
        store_path=store,
    )
    # Пустой API → нет строк; upsert в store не вызываем (не трогать существующий файл зря)
    assert recorded == []


def test_run_backfill_range_with_store_non_empty_upserts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой ответ API даёт 0 строк — upsert всё равно вызывается только при non-empty (см. код)."""
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    book = _minimal_bookmaker_node(seasons_nhl=[])
    book["snapshot_discovery"] = {
        "open_probe_offsets_hours": [24.0, 12.0],
        "close_margin_hours": 2.0,
    }
    cfg = OmegaConf.create({"bookmaker": book})
    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.load_bookmaker_config",
        lambda _k: cfg,
    )

    one_row = pd.DataFrame(
        [
            {
                "game_date": "2024-01-01",
                "home_team_norm": "A",
                "away_team_norm": "B",
                "pinnacle_home_open": 1.5,
                "pinnacle_away_open": 2.5,
                "pinnacle_draw_open": None,
                "pinnacle_home_close": 1.5,
                "pinnacle_away_close": 2.5,
                "pinnacle_draw_close": None,
                "pinnacle_total_open": 5.0,
                "pinnacle_total_close": 5.0,
            }
        ]
    )

    def fake_bdf(*a, **k):  # noqa: ANN002, ANN003
        return one_row

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.backfill_day_frames",
        fake_bdf,
    )

    class FakeClient:
        def last_quota(self) -> OddsApiQuotaSnapshot:
            return OddsApiQuotaSnapshot(requests_remaining=None, requests_used=None)

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.OddsApiClient",
        lambda *a, **k: FakeClient(),
    )

    recorded: list[int] = []

    def _upsert(df, path: Path):  # noqa: ANN001
        recorded.append(len(df))
        return df

    monkeypatch.setattr(backfill_mod, "upsert_odds_store_file", _upsert)

    store = tmp_path / "z.parquet"
    run_backfill(
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 1),
        store_path=store,
    )
    assert recorded == [1]


def test_upsert_if_non_empty_rejects_v2_invalid_line_before_file_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[int] = []

    def _u(_df: object, _path: object) -> None:  # noqa: ANN001
        called.append(1)

    monkeypatch.setattr(backfill_mod, "upsert_odds_store_file", _u)
    bad = pd.DataFrame(
        [
            {
                "pinnacle_winner_withOT_home_close": 1.9,
                "pinnacle_total_withOT_line_open": 0.1,
            }
        ]
    )
    with pytest.raises(RuntimeError, match="backfill: store"):
        backfill_mod._upsert_if_non_empty(
            bad,
            tmp_path / "x.parquet",
            context="backfill: store",  # noqa: SLF001
        )
    assert called == []


def test_upsert_if_non_empty_rejects_negative_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[int] = []

    def _u(_df: object, _path: object) -> None:  # noqa: ANN001
        called.append(1)

    monkeypatch.setattr(backfill_mod, "upsert_odds_store_file", _u)
    bad = pd.DataFrame([{"onexbet_winner_home_close": 1.8, "open_minutes_before": -1.0}])
    with pytest.raises(RuntimeError, match="t_open_m"):
        backfill_mod._upsert_if_non_empty(
            bad,
            tmp_path / "y.parquet",
            context="t_open_m",  # noqa: SLF001
        )
    assert called == []


def test_upsert_if_non_empty_accepts_v2_valid_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[str, int]] = []

    def _u(_df, path) -> None:  # noqa: ANN001
        called.append((str(path), len(_df)))  # noqa: SLF001

    monkeypatch.setattr(backfill_mod, "upsert_odds_store_file", _u)
    good = pd.DataFrame(
        [
            {
                "pinnacle_winner_withOT_home_close": 1.9,
                "pinnacle_total_withOT_line_open": 5.5,
                "open_minutes_before": 100.0,
            }
        ]
    )
    backfill_mod._upsert_if_non_empty(  # noqa: SLF001
        good,
        tmp_path / "z.parquet",
        context="t_ok",  # noqa: SLF001
    )
    assert len(called) == 1 and called[0][1] == 1


def test_backfill_stops_on_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    cfg = OmegaConf.create(
        {
            "bookmaker": _minimal_bookmaker_node(
                seasons_nhl=[
                    {
                        "name": "a",
                        "date_from": "2024-01-01",
                        "date_to": "2024-01-02",
                    }
                ],
                quota=1,
            )
        }
    )
    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.load_bookmaker_config",
        lambda _k: cfg,
    )
    # Реальный клиент: квота 1 — только один сетевой GET; backfill (2 снимка) упрётся в лимит.
    cfg_flat = cfg.bookmaker
    client = OddsApiClient(bookmaker_cfg=cfg_flat, cache_dir=tmp_path, max_real_http_requests=1)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": []}
    resp.raise_for_status = MagicMock()
    resp.headers = {}
    client._session = MagicMock()  # noqa: SLF001
    client._session.get.return_value = resp  # noqa: SLF001

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.OddsApiClient",
        lambda *a, **k: client,
    )

    _, hit = backfill_mod._backfill_date_range(
        client,
        cfg.bookmaker,
        date(2024, 1, 1),
        date(2024, 1, 1),
        sport_key="icehockey_nhl",
        regions="eu",
        use_open_close=True,
        team_registry=None,
        legacy_timestamps=True,
    )
    assert hit is True


def test_client_quota_raises_before_second_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "k")
    cfg = OmegaConf.create(
        {
            "name": "x",
            "api": {
                "base_url": "https://api.the-odds-api.com",
                "api_prefix": "/v4",
                "markets_h2h": ["h2h"],
                "markets_totals": ["totals"],
            },
            "bookmakers": {"primary": "pinnacle"},
            "rate_limit": {"min_interval_sec": 0.0},
        }
    )
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock()
    resp.headers = {}
    session = MagicMock()
    session.get.return_value = resp
    c = OddsApiClient(
        bookmaker_cfg=cfg, cache_dir=tmp_path, session=session, max_real_http_requests=1
    )
    c.get_json("/a", {"x": 1}, cache_key="k1", use_cache=False)
    with pytest.raises(QuotaBudgetError):
        c.get_json("/b", {"x": 2}, cache_key="k2", use_cache=False)
    assert session.get.call_count == 1


def _sample_odds_one_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_date": "2024-01-15",
                "home_team_norm": "A",
                "away_team_norm": "B",
                "pinnacle_home_open": 2.0,
                "pinnacle_away_open": 2.1,
                "pinnacle_draw_open": None,
                "pinnacle_home_close": 2.0,
                "pinnacle_away_close": 2.1,
                "pinnacle_draw_close": None,
                "pinnacle_total_open": 5.5,
                "pinnacle_total_close": 5.5,
            }
        ]
    )


def test_backfill_day_frames_discover_adds_timing_and_uses_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Режим по умолчанию: discover_snapshots_for_day; колонки тайминга; параметры из snapshot_discovery."""
    plan = SnapshotPlan(
        open_iso="2024-01-15T10:00:00Z",
        close_iso="2024-01-15T20:00:00Z",
        open_minutes_before=100,
        close_minutes_before=50,
        reference_commence_time_utc="2024-01-15T22:00:00Z",
        used_legacy_timestamps=False,
    )
    discover_calls: list[dict[str, object]] = []

    def _discover(  # noqa: ANN001
        _client, _sport_key, _day, **kwargs: object
    ) -> tuple[SnapshotPlan, dict[str, list[object]], dict[str, list[object]]]:
        discover_calls.append(kwargs)
        return (plan, {"data": []}, {"data": []})

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.discover_snapshots_for_day",
        _discover,
    )
    last_book_cfg: dict = {}

    def _eto(  # noqa: ANN001
        _ev_o, _ev_c, *_a, book_cfg=None, **kwargs: object
    ) -> pd.DataFrame:
        if book_cfg is not None and isinstance(book_cfg, dict):
            last_book_cfg.update(book_cfg)
        return _sample_odds_one_row()

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.events_to_odds_frame",
        _eto,
    )

    class _Dummy:
        pass

    book = _minimal_bookmaker_node(seasons_nhl=[])
    book["snapshot_discovery"] = {
        "open_probe_offsets_hours": [48.0, 24.0],
        "close_margin_hours": 1.5,
    }
    book["bookmaker_profiles"] = {
        "pinnacle": {
            "key": "pinnacle",
            "winner_semantics": "winner_withOT",
            "total_semantics": "total_withOT",
            "has_draw": False,
        }
    }
    df = backfill_day_frames(
        _Dummy(),  # type: ignore[arg-type]
        "icehockey_nhl",
        date(2024, 1, 15),
        book,
        legacy_timestamps=False,
    )
    assert len(df) == 1
    assert df["open_snapshot_utc"].iloc[0] == plan.open_iso
    assert df["close_snapshot_utc"].iloc[0] == plan.close_iso
    assert int(df["open_minutes_before"].iloc[0]) == 100
    assert int(df["close_minutes_before"].iloc[0]) == 50
    assert discover_calls
    assert discover_calls[0]["open_probe_offsets_hours"] == (48.0, 24.0)
    assert discover_calls[0]["close_margin_hours"] == 1.5
    assert "bookmaker_profiles" in last_book_cfg


def test_backfill_day_frames_legacy_no_discover_fixed_isos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """legacy_timestamps: два запроса по фиксированным ISO; discover не вызывается."""

    def _discover_boom(*_a, **_k):  # noqa: ANN202
        raise AssertionError("discover_snapshots_for_day must not run in legacy mode")

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.discover_snapshots_for_day",
        _discover_boom,
    )
    fetches: list[str] = []

    class C:
        def fetch_odds_for_sport(self, *a, **k):  # noqa: ANN002, ANN003
            di = k.get("date_iso") or ""
            fetches.append(str(di))
            return {"data": []}

    def _eto(_ev_o, _ev_c, *_, **__):  # noqa: ANN001
        return _sample_odds_one_row()

    monkeypatch.setattr(
        "sports_forecast.data.providers.odds.backfill.events_to_odds_frame",
        _eto,
    )
    book = _minimal_bookmaker_node(seasons_nhl=[])
    df = backfill_day_frames(
        C(),  # type: ignore[arg-type]
        "icehockey_nhl",
        date(2024, 1, 15),
        book,
        legacy_timestamps=True,
    )
    assert fetches[0] == "2024-01-15T12:00:00Z" and fetches[1] == "2024-01-15T23:30:00Z"
    assert df["open_snapshot_utc"].iloc[0] == "2024-01-15T12:00:00Z"
    assert df["close_snapshot_utc"].iloc[0] == "2024-01-15T23:30:00Z"
    assert int(df["open_minutes_before"].iloc[0]) == 0
    assert int(df["close_minutes_before"].iloc[0]) == 0


def test_main_passes_legacy_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "x")
    captured: dict[str, bool] = {}

    def _rb(*, legacy_timestamps, **kwargs):  # noqa: ANN003
        captured["legacy"] = bool(legacy_timestamps)

    monkeypatch.setattr(backfill_mod, "run_backfill", _rb)
    rc = main(
        [
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-01",
            "--legacy-timestamps",
        ]
    )
    assert rc == 0
    assert captured.get("legacy") is True
