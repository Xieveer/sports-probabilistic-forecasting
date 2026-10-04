"""Тесты live odds enrichment для prediction API (R37.5)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from omegaconf import OmegaConf

from sports_forecast.betting.edge_decision import EdgeDecisionParams
from sports_forecast.data.providers.odds.live_nhl_pinnacle import PinnacleH2HQuote
from sports_forecast.service import live_odds_enrichment
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.live_odds_enrichment import batch_live_response_extras
from sports_forecast.service.service_api_settings import reset_service_api_settings_cache


def _pred(**kwargs: object) -> Prediction:
    m = MagicMock(spec=Prediction)
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _reset_edge_cfg_cache() -> Generator[None, None, None]:
    reset_service_api_settings_cache()
    yield
    reset_service_api_settings_cache()


def test_live_pinnacle_disabled() -> None:
    p = _pred(
        id=1,
        match_id="m1",
        tournament="nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        home_player="TOR",
        away_player="BOS",
        match_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        predictions_json='{"home_win": 0.55, "away_win": 0.45}',
        proba_home=0.55,
        proba_away=0.45,
        model_version="v",
        algorithm="cb",
        featureset="adv",
        prediction_ts=datetime(2026, 1, 1, tzinfo=UTC),
        status="ok",
    )
    out = batch_live_response_extras([p], live_pinnacle=False)[1]
    assert out["live_odds_status"] == "disabled"


def test_skipped_not_nhl() -> None:
    p = _pred(
        id=2,
        match_id="x",
        tournament="uel_kz_1",
        market="winner",
        market_spec="winner",
        home_player="a",
        away_player="b",
        match_datetime=None,
        predictions_json="{}",
        proba_home=None,
        proba_away=None,
        model_version="v",
        algorithm="cb",
        featureset="adv",
        prediction_ts=datetime(2026, 1, 1, tzinfo=UTC),
        status="ok",
    )
    out = batch_live_response_extras([p], live_pinnacle=True)[2]
    assert out["live_odds_status"] == "skipped_not_nhl"


def test_skipped_unsupported_market() -> None:
    p = _pred(
        id=3,
        match_id="m",
        tournament="nhl",
        market="total_withOT",
        market_spec="total_over_withOT",
        home_player="TOR",
        away_player="BOS",
        match_datetime=None,
        predictions_json="{}",
        proba_home=None,
        proba_away=None,
        model_version="v",
        algorithm="cb",
        featureset="adv",
        prediction_ts=datetime(2026, 1, 1, tzinfo=UTC),
        status="ok",
    )
    out = batch_live_response_extras([p], live_pinnacle=True)[3]
    assert out["live_odds_status"] == "skipped_unsupported_market"


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    p = _pred(
        id=4,
        match_id="m",
        tournament="nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        home_player="TOR",
        away_player="BOS",
        match_datetime=None,
        predictions_json='{"home_win": 0.55, "away_win": 0.45}',
        proba_home=0.55,
        proba_away=None,
        model_version="v",
        algorithm="cb",
        featureset="adv",
        prediction_ts=datetime(2026, 1, 1, tzinfo=UTC),
        status="ok",
    )
    out = batch_live_response_extras([p], live_pinnacle=True)[4]
    assert out["live_odds_status"] == "missing_api_key"


def test_fetch_maps_quote_and_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "dummy")
    p = _pred(
        id=5,
        match_id="m99",
        tournament="nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        home_player="TOR",
        away_player="BOS",
        match_datetime=None,
        predictions_json='{"home_win": 0.55, "away_win": 0.45}',
        proba_home=0.55,
        proba_away=None,
        model_version="v",
        algorithm="cb",
        featureset="adv",
        prediction_ts=datetime(2026, 1, 1, tzinfo=UTC),
        status="ok",
    )
    fake_quote = PinnacleH2HQuote(
        odds_api_event_id="e1",
        home_team="TOR",
        away_team="BOS",
        commence_utc=None,
        decimal_home=2.0,
        decimal_away=2.0,
    )

    def _fake_fetch(
        *_a: object,
        **_kw: object,
    ) -> dict[str, PinnacleH2HQuote | None]:
        return {"m99": fake_quote}

    with (
        patch(
            "sports_forecast.service.live_odds_enrichment.fetch_nhl_pinnacle_quotes_for_refs",
            side_effect=_fake_fetch,
        ),
        patch(
            "sports_forecast.service.live_odds_enrichment.load_edge_decision_params",
            return_value=EdgeDecisionParams(edge_threshold=0.01, min_odds=1.01),
        ),
    ):
        out = batch_live_response_extras([p], live_pinnacle=True)[5]

    assert out["pinnacle_home_decimal"] == pytest.approx(2.0)
    assert out["edge_home"] == pytest.approx(0.05)
    assert out["edge_away"] == pytest.approx(-0.05)
    assert out["bet_decision_home"] == "bet"
    assert out["bet_decision_away"] == "no_bet"
    assert out["live_odds_status"] == "ok"


def test_live_registry_mode_needs_confirmed_quote_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live путь применяет pinned registry после получения bookmaker payload."""
    p = _pred(
        id=6,
        match_id="m99",
        tournament="nhl",
        market="winner_withOT",
        home_player="TOR",
        away_player="BOS",
        match_datetime=datetime(2026, 1, 10, tzinfo=UTC),
        proba_home=0.55,
        predictions_json='{"home_win":0.55}',
    )
    payload = [
        {
            "id": "e1",
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
                                {"name": "TOR", "price": 2.0},
                                {"name": "BOS", "price": 2.0},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    client = MagicMock()
    client.fetch_odds_for_sport.return_value = payload
    cfg = OmegaConf.create(
        {
            "bookmaker": {
                "sport_keys": {"nhl": "icehockey_nhl"},
                "bookmakers": {"primary": "pinnacle"},
                "live_inference": {"event_id_to_match_id": {"e1": "m99"}},
            }
        }
    )
    resolved: dict[str, str | None] = {"quote": None}
    canonical = SimpleNamespace(id=9, sport="ice_hockey")

    class FakeSession:
        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [canonical])

    @contextmanager
    def fake_session():
        yield FakeSession()

    class FakeReader:
        event_snapshot = SimpleNamespace(
            resolve=lambda _ref: SimpleNamespace(
                status="resolved" if resolved["quote"] else "unresolved",
                project_event_id=resolved["quote"],
            )
        )

        def get_event_mapping(self, _event_id, _session):
            return SimpleNamespace(status="resolved", project_event_id="project-1")

    monkeypatch.setattr(live_odds_enrichment, "registry_event_reader_enabled", lambda: True)
    monkeypatch.setattr(live_odds_enrichment, "get_session", fake_session)
    monkeypatch.setattr(live_odds_enrichment, "pin_installed_registry", lambda _s: FakeReader())
    monkeypatch.setattr(live_odds_enrichment, "load_bookmaker_config", lambda _name: cfg)
    monkeypatch.setattr(live_odds_enrichment, "build_odds_client_for_live", lambda _cfg: client)
    monkeypatch.setattr(live_odds_enrichment, "_registry", lambda: None)

    assert live_odds_enrichment._fetch_quotes_map([p])["m99"] is None
    resolved["quote"] = "project-1"
    assert live_odds_enrichment._fetch_quotes_map([p])["m99"] is not None
