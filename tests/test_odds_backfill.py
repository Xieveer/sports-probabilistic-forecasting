"""Тесты CLI/логики backfill The Odds API (сезоны, store, квота)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds import backfill as backfill_mod
from sports_forecast.data.providers.odds.backfill import (
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
    import pandas as pd

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    cfg = OmegaConf.create({"bookmaker": _minimal_bookmaker_node(seasons_nhl=[])})
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
