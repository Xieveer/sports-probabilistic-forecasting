"""Форматирование ответа API в Telegram-обработчике predict (R37.7)."""

from __future__ import annotations

from omegaconf import OmegaConf

from sports_forecast.bot.handlers.predict import (
    _format_live_lines,
    _format_prediction_card,
    _format_upcoming_line,
    _is_nhl_tournament,
    _upcoming_query_params,
)


def test_is_nhl_tournament() -> None:
    assert _is_nhl_tournament("nhl") is True
    assert _is_nhl_tournament("NHL_train") is True
    assert _is_nhl_tournament("uel_kz_1") is False


def test_upcoming_query_params_nhl_live_on() -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://x", "live_pinnacle": True}})
    p = _upcoming_query_params("nhl", cfg)
    assert p == {
        "live_pinnacle": True,
        "market": "winner_withOT",
        "market_spec": "winner_withOT",
    }


def test_upcoming_query_params_uel_no_market_override() -> None:
    cfg = OmegaConf.create({"bot": {"live_pinnacle": True}})
    p = _upcoming_query_params("uel_kz_1", cfg)
    assert p == {"live_pinnacle": True}


def test_upcoming_query_params_live_off() -> None:
    cfg = OmegaConf.create({"bot": {"live_pinnacle": False}})
    p = _upcoming_query_params("nhl", cfg)
    assert p == {"market": "winner_withOT", "market_spec": "winner_withOT"}


def test_upcoming_query_params_live_default_when_key_absent() -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://127.0.0.1:8000"}})
    p = _upcoming_query_params("uel_kz_1", cfg)
    assert p == {"live_pinnacle": True}


def test_format_live_lines_missing_api_key() -> None:
    lines = _format_live_lines({"live_odds_status": "missing_api_key"})
    assert len(lines) == 1
    assert "ODDS_API_KEY" in lines[0]


def test_format_live_lines_ok_with_edge() -> None:
    item = {
        "live_odds_status": "ok",
        "pinnacle_home_decimal": 2.0,
        "pinnacle_away_decimal": 2.2,
        "edge_home": 0.05,
        "edge_away": -0.02,
        "bet_decision_home": "bet",
        "bet_decision_away": "no_bet",
    }
    lines = _format_live_lines(item)
    assert any("Pinnacle" in x for x in lines)
    assert any("Edge home" in x for x in lines)
    assert any("Edge away" in x for x in lines)
    assert any("ставка" in x for x in lines)
    assert any("away ML" in x for x in lines)


def test_format_prediction_card_includes_live() -> None:
    item = {
        "match_id": "m1",
        "match_datetime": "2026-01-01T12:00:00",
        "home_player": "A",
        "away_player": "B",
        "predictions": {"home_win": 0.6},
        "live_odds_status": "ok",
        "pinnacle_home_decimal": 2.0,
        "pinnacle_away_decimal": 2.0,
        "edge_home": 0.1,
        "edge_away": -0.05,
        "bet_decision_home": "no_bet",
        "bet_decision_away": "bet",
    }
    text = _format_prediction_card(item)
    assert "Edge home" in text
    assert "Edge away" in text
    assert "нет ставки" in text
    assert "ставка" in text


def test_format_upcoming_line_indents_live() -> None:
    item = {
        "home_player": "A",
        "away_player": "B",
        "match_datetime": "2026-01-01",
        "live_odds_status": "missing_api_key",
    }
    text = _format_upcoming_line(item)
    assert "A — B" in text
    assert "  " in text
    assert "ODDS_API_KEY" in text
