"""Unit tests for live NHL Pinnacle mapping (R37.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.odds.client import OddsApiClient, QuotaBudgetError
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
    NHLLiveMatchRef,
    build_odds_client_for_live,
    fetch_nhl_pinnacle_quotes_for_refs,
    map_match_refs_to_pinnacle_quotes,
    parse_pinnacle_h2h_quotes_from_payload,
)


def _sample_payload() -> list[dict[str, object]]:
    return [
        {
            "id": "evt_tor_bos",
            "home_team": "TOR",
            "away_team": "BOS",
            "commence_time": "2026-01-10T00:00:00Z",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "TOR", "price": 1.95},
                                {"name": "BOS", "price": 2.05},
                            ],
                        }
                    ],
                }
            ],
        },
        {
            "id": "evt_no_pin",
            "home_team": "NYR",
            "away_team": "NYI",
            "commence_time": "2026-01-11T00:00:00Z",
            "bookmakers": [],
        },
    ]


def test_parse_pinnacle_skips_empty_bookmaker() -> None:
    quotes = parse_pinnacle_h2h_quotes_from_payload(
        _sample_payload(),
        bookmaker_key="pinnacle",
    )
    assert len(quotes) == 1
    assert quotes[0].odds_api_event_id == "evt_tor_bos"
    assert quotes[0].decimal_home == pytest.approx(1.95)
    assert quotes[0].decimal_away == pytest.approx(2.05)


def test_map_override_wins() -> None:
    quotes = parse_pinnacle_h2h_quotes_from_payload(
        _sample_payload(),
        bookmaker_key="pinnacle",
    )
    refs = [
        NHLLiveMatchRef(
            match_id="999",
            home_team="X",
            away_team="Y",
            commence_utc=None,
        )
    ]
    out = map_match_refs_to_pinnacle_quotes(
        refs,
        quotes,
        commence_tolerance_minutes=1,
        event_id_to_match_id={"evt_tor_bos": "999"},
    )
    assert out["999"] is not None
    assert out["999"].odds_api_event_id == "evt_tor_bos"


def test_map_by_team_and_commence_tolerance() -> None:
    quotes = parse_pinnacle_h2h_quotes_from_payload(
        _sample_payload(),
        bookmaker_key="pinnacle",
    )
    ref_time = datetime(2026, 1, 10, 0, 15, tzinfo=timezone.utc)
    refs = [
        NHLLiveMatchRef(
            match_id="m1",
            home_team="TOR",
            away_team="BOS",
            commence_utc=ref_time,
        )
    ]
    out = map_match_refs_to_pinnacle_quotes(
        refs,
        quotes,
        commence_tolerance_minutes=60,
    )
    assert out["m1"] is not None
    assert out["m1"].decimal_home == pytest.approx(1.95)


def test_map_rejects_when_commence_outside_tolerance() -> None:
    quotes = parse_pinnacle_h2h_quotes_from_payload(
        _sample_payload(),
        bookmaker_key="pinnacle",
    )
    ref_time = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    refs = [
        NHLLiveMatchRef(
            match_id="m1",
            home_team="TOR",
            away_team="BOS",
            commence_utc=ref_time,
        )
    ]
    out = map_match_refs_to_pinnacle_quotes(
        refs,
        quotes,
        commence_tolerance_minutes=60,
    )
    assert out["m1"] is None


def test_build_odds_client_respects_live_max_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "dummy-test-key")
    cfg = OmegaConf.create(
        {
            "bookmaker": {
                "api": {"base_url": "https://api.the-odds-api.com", "api_prefix": "/v4"},
                "live_inference": {"max_real_http_requests": 7},
            }
        }
    )
    c = build_odds_client_for_live(cfg)
    assert c._max_real_http_requests == 7  # noqa: SLF001


def test_quota_budget_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """При исчерпании ``max_real_http_requests`` следующий fetch не уходит в сеть."""
    monkeypatch.setenv("ODDS_API_KEY", "dummy-test-key")
    cfg = OmegaConf.create(
        {
            "bookmaker": {
                "api": {"base_url": "https://api.the-odds-api.com", "api_prefix": "/v4"},
                "live_inference": {"max_real_http_requests": 1},
            }
        }
    )
    client = OddsApiClient(cfg, max_real_http_requests=1)
    client._real_http_requests = 1  # noqa: SLF001 — имитация уже израсходованной квоты
    with pytest.raises(QuotaBudgetError):
        client.fetch_odds_for_sport("icehockey_nhl", use_cache=False)


def test_fetch_with_injected_client_no_network() -> None:
    cfg = OmegaConf.create(
        {
            "bookmaker": {
                "sport_keys": {"nhl": "icehockey_nhl"},
                "bookmakers": {"primary": "pinnacle"},
                "live_inference": {
                    "regions": "us",
                    "commence_tolerance_minutes": 360,
                    "event_id_to_match_id": {},
                },
            }
        }
    )
    mock_client = MagicMock()
    mock_client.fetch_odds_for_sport.return_value = _sample_payload()
    refs = [
        NHLLiveMatchRef(
            match_id="m1",
            home_team="TOR",
            away_team="BOS",
            commence_utc=datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
    ]
    out = fetch_nhl_pinnacle_quotes_for_refs(refs, book_cfg=cfg, client=mock_client)
    assert out["m1"] is not None
    mock_client.fetch_odds_for_sport.assert_called_once()
    call_kw = mock_client.fetch_odds_for_sport.call_args
    assert call_kw[0][0] == "icehockey_nhl"
    assert call_kw[1]["markets"] == ["h2h"]
