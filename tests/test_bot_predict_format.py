"""Форматирование ответа API в Telegram-обработчике predict (R37.7)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.types import Chat, InaccessibleMessage, Message
from omegaconf import OmegaConf

from sports_forecast.bot.handlers.predict import (
    SCHEDULE_PERIODS,
    _format_calendar,
    _format_live_lines,
    _format_prediction_card,
    _format_upcoming_line,
    _is_nhl_tournament,
    _kb_schedule_periods,
    _kb_schedule_tournaments,
    _send_schedule,
    _split_schedule_messages,
    _upcoming_query_params,
    cb_schedule_tournament,
    cmd_upcoming,
    fetch_schedule,
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
    assert "/upcoming — календарь NHL: сегодня, завтра, 3/7/14/30 дней" in text
    assert "/upcoming [турнир]" not in text


def test_schedule_tournament_requests_period_and_persists_choice(monkeypatch) -> None:
    message = Message(message_id=1, date=datetime(2026, 1, 1), chat=Chat(id=1, type="private"))
    answer = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)
    query = SimpleNamespace(data="schedule:nhl", message=message, answer=AsyncMock())
    state = _ScheduleState()

    asyncio.run(cb_schedule_tournament(query, state))

    assert state.data == {"schedule_tournament": "nhl"}
    assert state.state is not None
    answer.assert_awaited_once()
    assert "08:00–08:00 МСК" in answer.await_args.args[0]
    query.answer.assert_awaited_once()


def test_schedule_period_keyboard_has_only_contract_values() -> None:
    keyboard = _kb_schedule_periods()
    assert [button.callback_data for row in keyboard.inline_keyboard for button in row] == [
        f"period:{period}" for period in SCHEDULE_PERIODS
    ]


def test_fetch_schedule_uses_calendar_endpoint_and_fixed_period(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api", "live_pinnacle": False}})
    captured: dict[str, object] = {}

    async def fake_fetch(_client, url, *, params=None):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["params"] = params
        return {"events": [], "total": 0, "coverage": {"status": "confirmed_empty"}}

    monkeypatch.setattr("sports_forecast.bot.handlers.predict._fetch_json", fake_fetch)

    result = asyncio.run(
        fetch_schedule(cast(httpx.AsyncClient, object()), cfg=cfg, tournament="nhl", period="3")
    )
    assert result["coverage"]["status"] == "confirmed_empty"
    assert captured["url"] == "http://api/calendar/nhl"
    assert captured["params"] == {"period": "3", "limit": 50, "offset": 0}


def test_fetch_schedule_passes_each_supported_period(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})
    requests: list[dict[str, object]] = []

    async def fake_fetch(_client, _url, *, params=None):  # type: ignore[no-untyped-def]
        requests.append(params)
        return {"events": [], "total": 0, "coverage": {"status": "confirmed_empty"}}

    monkeypatch.setattr("sports_forecast.bot.handlers.predict._fetch_json", fake_fetch)
    for period in SCHEDULE_PERIODS:
        asyncio.run(
            fetch_schedule(
                cast(httpx.AsyncClient, object()), cfg=cfg, tournament="nhl", period=period
            )
        )

    assert [request["period"] for request in requests] == list(SCHEDULE_PERIODS)


def test_fetch_schedule_rejects_period_outside_calendar_contract() -> None:
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})
    with pytest.raises(ValueError, match="Недопустимый период"):
        asyncio.run(
            fetch_schedule(cast(httpx.AsyncClient, object()), cfg=cfg, tournament="nhl", period="0")
        )


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        ("confirmed_empty", "пустое окно подтверждено источником"),
        ("incomplete", "покрытие календаря неполное"),
        ("stale", "данные календаря устарели"),
        ("unavailable", "обновление календаря завершилось ошибкой"),
    ],
)
def test_empty_calendar_explains_coverage_state(monkeypatch, coverage: str, expected: str) -> None:
    message = _message()
    state = _ScheduleState({"schedule_tournament": "nhl"})
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})

    async def fake_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"events": [], "total": 0, "coverage": {"status": coverage}}

    monkeypatch.setattr("sports_forecast.bot.handlers.predict.fetch_schedule", fake_fetch)
    asyncio.run(_send_schedule(message, state, cfg, "today"))

    text = message.answer.await_args.args[0]
    assert expected in text
    if coverage != "confirmed_empty":
        assert "Список матчей может быть неполным." in text


def test_calendar_api_failure_is_not_reported_as_empty(monkeypatch) -> None:
    message = _message()
    state = _ScheduleState({"schedule_tournament": "nhl"})
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api"}})

    async def failed_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise httpx.ConnectError("internal test detail")

    monkeypatch.setattr("sports_forecast.bot.handlers.predict.fetch_schedule", failed_fetch)
    asyncio.run(_send_schedule(message, state, cfg, "today"))

    message.answer.assert_awaited_once_with("Расписание временно недоступно.")
    assert state.cleared is False


def test_format_calendar_groups_events_and_shows_independent_readiness() -> None:
    text = _format_calendar(
        [
            {
                "home_participant": "A",
                "away_participant": "B",
                "scheduled_at": "2026-09-16T22:00:00Z",
                "status": "scheduled",
                "calendar_readiness": "current",
                "prediction_readiness": {"status": "ready"},
                "odds_readiness": {"status": "stale"},
                "readiness": {"status": "partial"},
            },
            {
                "home_participant": "C",
                "away_participant": "D",
                "scheduled_at": "2026-09-17T22:00:00Z",
                "calendar_readiness": "current",
                "prediction_readiness": {"status": "pending"},
                "odds_readiness": {"status": "missing"},
                "readiness": {"status": "waiting"},
            },
            {
                "home_participant": "E",
                "away_participant": "F",
                "scheduled_at": "2026-09-18T22:00:00Z",
                "status": "postponed",
                "calendar_readiness": "postponed",
                "prediction_readiness": {"status": "pending"},
                "odds_readiness": {"status": "missing"},
                "readiness": {"status": "waiting"},
            },
            {
                "home_participant": "G",
                "away_participant": "H",
                "scheduled_at": "2026-09-19T22:00:00Z",
                "status": "cancelled",
                "calendar_readiness": "cancelled",
                "prediction_readiness": {"status": "pending"},
                "odds_readiness": {"status": "missing"},
                "readiness": {"status": "waiting"},
            },
        ]
    )
    assert "17 сентября" in text
    assert "18 сентября" in text
    assert "01:00 МСК" in text
    assert "—————————————————————————————" in text
    assert "Календарь: актуален" in text
    assert "Прогноз: готово" in text
    assert "Коэффициенты: устарело" in text
    assert "Готовность: частично готово" in text
    assert "Прогноз: ожидает" in text
    assert "Коэффициенты: нет данных" in text
    assert "Календарь: перенесён" in text
    assert "Календарь: отменён" in text


def test_split_schedule_messages_keeps_every_match_without_truncation() -> None:
    items = [
        {
            "home_participant": f"Home {index}",
            "away_participant": f"Away {index}",
            "scheduled_at": "2026-09-16T20:00:00Z",
            "calendar_readiness": "current",
            "prediction_readiness": {"status": "pending"},
            "odds_readiness": {"status": "missing"},
            "readiness": {"status": "waiting"},
        }
        for index in range(80)
    ]

    messages = _split_schedule_messages(items, limit=800)

    assert len(messages) > 1
    assert all(len(message) <= 800 for message in messages)
    assert all(f"Home {index} — Away {index}" in "\n".join(messages) for index in range(80))


def test_split_schedule_messages_keeps_html_entities_and_emoji_intact() -> None:
    items = [
        {
            "home_participant": "&" * 1000,
            "away_participant": "🏒" * 1000,
            "scheduled_at": "2026-09-16T20:00:00Z",
            "calendar_readiness": "current",
            "prediction_readiness": {"status": "pending"},
            "odds_readiness": {"status": "missing"},
            "readiness": {"status": "waiting"},
        }
    ]

    messages = _split_schedule_messages(items)

    assert all(len(message) <= 4000 for message in messages)
    for message in messages:
        assert re.search(r"&amp;", message)
        assert all(
            re.match(r"&(amp|lt|gt|quot|#x27);", message[index:])
            for index, char in enumerate(message)
            if char == "&"
        )
        assert "🏒" in message


def test_split_schedule_messages_measures_telegram_utf16_limit() -> None:
    items = [
        {
            "home_participant": "🏒" * 128,
            "away_participant": "🏒" * 128,
            "scheduled_at": "2026-09-16T20:00:00Z",
            "calendar_readiness": "current",
            "prediction_readiness": {"status": "pending"},
            "odds_readiness": {"status": "missing"},
            "readiness": {"status": "waiting"},
        }
        for _ in range(15)
    ]

    messages = _split_schedule_messages(items)

    assert len(messages) > 1
    assert all(len(message.encode("utf-16-le")) // 2 <= 4000 for message in messages)


def test_old_schedule_callback_handles_inaccessible_message() -> None:
    callback = SimpleNamespace(
        data="schedule:nhl",
        message=InaccessibleMessage(
            chat=Chat(id=123, type="private"),
            message_id=456,
            date=0,
        ),
        answer=AsyncMock(),
    )
    state = _ScheduleState()

    asyncio.run(cb_schedule_tournament(callback, state))

    callback.answer.assert_awaited_once()
    assert state.data == {}


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
