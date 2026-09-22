"""Форматирование ответа API в Telegram-обработчике predict (R37.7)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
from omegaconf import OmegaConf

from sports_forecast.bot.handlers.predict import (
    _format_live_lines,
    _format_prediction_card,
    _format_schedule,
    _format_upcoming_line,
    _is_nhl_tournament,
    _kb_schedule_tournaments,
    _schedule_window,
    _schedule_window_hours,
    _split_schedule_messages,
    _upcoming_query_params,
    cb_schedule_tournament,
    cmd_upcoming,
    fetch_schedule,
    schedule_days,
)
from sports_forecast.bot.handlers.start import cmd_help


class _ScheduleState:
    """Минимальная in-memory реализация состояния для контрактных тестов handler-а."""

    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = data or {}
        self.state: object | None = None
        self.cleared = False

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state: object) -> None:
        self.state = state

    async def get_data(self) -> dict[str, object]:
        return self.data

    async def clear(self) -> None:
        self.cleared = True


def _message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, answer=AsyncMock())


def test_schedule_tournament_keyboard_is_limited_to_nhl() -> None:
    keyboard = _kb_schedule_tournaments()
    assert [
        (button.text, button.callback_data) for row in keyboard.inline_keyboard for button in row
    ] == [("NHL", "schedule:nhl")]


def test_upcoming_starts_with_nhl_choice() -> None:
    message = _message("/upcoming")

    asyncio.run(cmd_upcoming(message))

    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Выберите турнир:"
    assert (
        message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
        == "schedule:nhl"
    )


def test_help_describes_schedule_without_obsolete_tournament_argument() -> None:
    message = _message("/help")

    asyncio.run(cmd_help(message))

    text = message.answer.await_args.args[0]
    assert "/upcoming — расписание NHL на выбранное число дней" in text
    assert "/upcoming [турнир]" not in text


def test_schedule_tournament_requests_days_and_persists_choice() -> None:
    message = _message()
    query = SimpleNamespace(data="schedule:nhl", message=message, answer=AsyncMock())
    state = _ScheduleState()

    asyncio.run(cb_schedule_tournament(query, state))

    assert state.data == {"schedule_tournament": "nhl"}
    assert state.state is not None
    message.answer.assert_awaited_once_with("Введите число дней от 0 до 30 (0 — до конца сегодня):")
    query.answer.assert_awaited_once()


def test_schedule_days_rejects_invalid_range_without_api_call(monkeypatch) -> None:
    message = _message("31")
    state = _ScheduleState({"schedule_tournament": "nhl"})
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})
    fetch = AsyncMock()
    monkeypatch.setattr("sports_forecast.bot.handlers.predict.fetch_schedule", fetch)

    asyncio.run(schedule_days(message, state, cfg))

    message.answer.assert_awaited_once_with("Введите число от 0 до 30.")
    fetch.assert_not_awaited()
    assert state.cleared is False


def test_schedule_days_returns_empty_result_and_clears_state(monkeypatch) -> None:
    message = _message("0")
    state = _ScheduleState({"schedule_tournament": "nhl"})
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})

    async def fake_fetch(*_args: object, **kwargs: object) -> dict[str, list[object]]:
        assert kwargs["tournament"] == "nhl"
        assert kwargs["days"] == 0
        return {"predictions": []}

    monkeypatch.setattr("sports_forecast.bot.handlers.predict.fetch_schedule", fake_fetch)

    asyncio.run(schedule_days(message, state, cfg))

    assert state.cleared is True
    message.answer.assert_awaited_once_with("В выбранном периоде будущих матчей нет.")


def test_schedule_days_handles_malformed_successful_response(monkeypatch) -> None:
    message = _message("1")
    state = _ScheduleState({"schedule_tournament": "nhl"})
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})

    async def fake_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise json.JSONDecodeError("Некорректный JSON", "<html>", 0)

    monkeypatch.setattr("sports_forecast.bot.handlers.predict.fetch_schedule", fake_fetch)

    asyncio.run(schedule_days(message, state, cfg))

    assert state.cleared is False
    message.answer.assert_awaited_once_with("Расписание временно недоступно.")


def test_fetch_schedule_passes_calendar_horizon(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api", "live_pinnacle": False}})
    captured: dict[str, object] = {}

    async def fake_fetch(_client, url, *, params=None):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["params"] = params
        return {"predictions": []}

    monkeypatch.setattr("sports_forecast.bot.handlers.predict._fetch_json", fake_fetch)

    result = asyncio.run(
        fetch_schedule(cast(httpx.AsyncClient, object()), cfg=cfg, tournament="nhl", days=3)
    )
    assert result == {"predictions": []}
    assert captured["url"] == "http://api/predict/upcoming/nhl"
    assert isinstance(captured["params"], dict)
    assert captured["params"]["hours"] > 48


def test_schedule_window_zero_ends_today_moscow() -> None:
    now = datetime(2026, 9, 16, 20, 30, tzinfo=UTC)
    assert _schedule_window_hours(0, now=now) == 1
    start, deadline = _schedule_window(0, now=now)
    assert start == now
    assert deadline == datetime(2026, 9, 16, 20, 59, 59, 999999, tzinfo=UTC)


def test_format_schedule_groups_by_moscow_day_and_marks_missing_data() -> None:
    text = _format_schedule(
        [
            {
                "home_player": "A",
                "away_player": "B",
                "match_datetime": "2026-09-16T22:00:00",
                "predictions": {"home": 0.6},
                "edge_home": 0.05,
                "edge_away": -0.02,
                "pinnacle_home_decimal": 2.0,
                "pinnacle_away_decimal": 2.2,
                "bet_decision_home": "bet",
                "bet_decision_away": "no_bet",
            },
            {
                "home_player": "C",
                "away_player": "D",
                "match_datetime": "2026-09-17T22:00:00",
            },
        ]
    )
    assert "17 сентября" in text
    assert "18 сентября" in text
    assert "01:00 МСК" in text
    assert "Value: home +0.0500 | away -0.0200" in text
    assert "Коэффициенты: home 2.00 | away 2.20" in text
    assert "Решение: home ставка | away нет ставки" in text
    assert "Прогноз: нет данных" in text


def test_fetch_schedule_filters_item_after_exact_moscow_deadline(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api", "live_pinnacle": False}})

    async def fake_fetch(_client, _url, *, params=None):  # type: ignore[no-untyped-def]
        assert params["hours"] == 1
        return {
            "predictions": [
                {"match_datetime": "2026-09-16T20:45:00"},
                {"match_datetime": "2026-09-16T21:15:00"},
            ]
        }

    monkeypatch.setattr("sports_forecast.bot.handlers.predict._fetch_json", fake_fetch)
    now = datetime(2026, 9, 16, 20, 30, tzinfo=UTC)
    result = asyncio.run(
        fetch_schedule(
            cast(httpx.AsyncClient, object()), cfg=cfg, tournament="nhl", days=0, now=now
        )
    )

    assert result["predictions"] == [{"match_datetime": "2026-09-16T20:45:00"}]


def test_split_schedule_messages_keeps_every_match_without_truncation() -> None:
    items = [
        {
            "home_player": f"Home {index}",
            "away_player": f"Away {index}",
            "match_datetime": "2026-09-16T20:00:00",
            "predictions": {"home": 0.5},
        }
        for index in range(80)
    ]

    messages = _split_schedule_messages(items, limit=800)

    assert len(messages) > 1
    assert all(len(message) <= 800 for message in messages)
    assert all(f"Home {index} — Away {index}" in "\n".join(messages) for index in range(80))


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
