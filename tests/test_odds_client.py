"""Тесты OddsApiClient (кэш, заголовки квоты, без реального API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds.client import OddsApiClient


@pytest.fixture
def odds_cfg_dict() -> dict:
    return {
        "name": "the_odds_api",
        "api": {
            "base_url": "https://api.the-odds-api.com",
            "api_prefix": "/v4",
            "markets_h2h": ["h2h"],
            "markets_totals": ["totals"],
        },
        "bookmakers": {"primary": "pinnacle"},
        "rate_limit": {"min_interval_sec": 0.0},
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
    }


def test_odds_client_cache_hit(
    tmp_path: Path,
    odds_cfg_dict: dict,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    cfg = OmegaConf.create(odds_cfg_dict)
    session = MagicMock()
    client = OddsApiClient(bookmaker_cfg=cfg, cache_dir=tmp_path, session=session)

    payload: dict[str, Any] = {"data": []}
    cache_key = "test_key"
    cpath = client._cache_path(cache_key)
    cpath.write_text(json.dumps(payload), encoding="utf-8")

    with caplog.at_level("INFO"):
        out = client.get_json(
            "/sports/x/odds", {"regions": "eu"}, cache_key=cache_key, use_cache=True
        )
    assert out == payload
    session.get.assert_not_called()
    assert "cached=True" in caplog.text
    assert "test-key" not in caplog.text
    assert "/sports/x/odds" in caplog.text


def test_quota_headers(
    tmp_path: Path,
    odds_cfg_dict: dict,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    cfg = OmegaConf.create(odds_cfg_dict)
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-requests-remaining": "42", "x-requests-used": "8"}
    resp.json.return_value = []
    resp.raise_for_status = MagicMock()
    session = MagicMock()
    session.get.return_value = resp

    client = OddsApiClient(bookmaker_cfg=cfg, cache_dir=tmp_path, session=session)
    with caplog.at_level("INFO"):
        client.get_json("/z", {"a": 1}, cache_key="k2", use_cache=False)
    q = client.last_quota()
    assert q.requests_remaining == 42
    assert q.requests_used == 8
    assert "status=200" in caplog.text
    assert "x-requests-remaining=42" in caplog.text
    assert "cached=False" in caplog.text
    assert "test-key" not in caplog.text


def test_live_request_without_cache_does_not_persist_key_or_response(
    tmp_path: Path,
    odds_cfg_dict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``use_cache=False`` не создаёт файл кэша и не раскрывает ключ в имени."""
    monkeypatch.setenv("ODDS_API_KEY", "secret-api-key")
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.return_value = []
    resp.raise_for_status = MagicMock()
    session = MagicMock()
    session.get.return_value = resp

    cache_dir = tmp_path / "cache"
    client = OddsApiClient(
        bookmaker_cfg=OmegaConf.create(odds_cfg_dict), cache_dir=cache_dir, session=session
    )
    client.get_json("/sports/x/odds", {"regions": "eu"}, use_cache=False)

    assert not cache_dir.exists()


def test_cache_filename_hashes_explicit_key_without_secret(
    tmp_path: Path,
    odds_cfg_dict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Имя файла кэша не раскрывает даже явно переданный секретный ключ."""
    monkeypatch.setenv("ODDS_API_KEY", "secret-api-key")
    client = OddsApiClient(bookmaker_cfg=OmegaConf.create(odds_cfg_dict), cache_dir=tmp_path)

    cache_path = client._cache_path("contains-secret-api-key")

    assert "secret-api-key" not in cache_path.name
