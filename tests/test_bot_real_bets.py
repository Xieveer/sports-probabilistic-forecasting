"""Ручной сценарий записи и расчёта ставок владельца."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from omegaconf import OmegaConf

from sports_forecast.bot.handlers import real_bets


class FakeState:
    """Минимальное состояние диалога для проверки последовательности шагов."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state: object | None = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, value: object) -> None:
        self.state = value

    async def clear(self) -> None:
        self.data.clear()
        self.state = None


def _message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=101),
        chat=SimpleNamespace(type="private", id=101),
        message_id=42,
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
    )


def _callback(data: str, message: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=101),
        message=message or _message(),
        answer=AsyncMock(),
    )


def test_owner_records_cash_bet_from_immutable_card_and_confirms(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    context_id = "12345678-1234-1234-1234-123456789abc"
    requests: list[tuple[str, str, dict | None, str | None]] = []

    async def control(_cfg, _owner, method, path, *, payload=None, idempotency_key=None, **_kwargs):
        requests.append((method, path, payload, idempotency_key))
        if method == "GET":
            return {
                "context_id": context_id,
                "prediction_revision_id": None,
                "quote_observation_id": None,
                "prediction": {
                    "home_player": "WSH",
                    "away_player": "SEA",
                    "market_spec": "winner_withOT",
                    "predictions": {"home_win": 0.6, "away_win": 0.4},
                },
            }
        return {"bet_id": "bet-1"}

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message()
    asyncio.run(real_bets.cb_new_bet(_callback(f"bet:new:{context_id}", message), cfg, state))
    asyncio.run(real_bets.cb_bet_outcome(_callback("bet:outcome:0", message), cfg, state))
    asyncio.run(real_bets.cb_bet_funding(_callback("bet:funding:cash", message), cfg, state))
    asyncio.run(real_bets.msg_bet_stake(_message("100,50"), cfg, state))
    asyncio.run(real_bets.msg_bet_odds(_message("2,35"), cfg, state))
    asyncio.run(real_bets.cb_bet_placed(_callback("bet:placed:now", message), cfg, state))
    preview = message.answer.await_args.args[0]
    assert "Winline: 100.50 ₽ × 2.35" in preview
    assert "нет подтверждённой" in preview
    asyncio.run(real_bets.cb_bet_confirm(_callback("bet:confirm", message), cfg, state))
    assert requests[-1][0:2] == ("POST", "bets")
    assert requests[-1][2]["stake"] == "100.50"
    assert requests[-1][2]["outcome"] == "home_win"
    assert requests[-1][3]
    assert state.data == {}


def test_freebet_void_settlement_uses_zero_payout(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    bet_id = "12345678-1234-1234-1234-123456789abc"
    requests: list[tuple[str, str, dict | None]] = []

    async def control(_cfg, _owner, method, path, *, payload=None, **_kwargs):
        requests.append((method, path, payload))
        if method == "GET":
            return {
                "bet_id": bet_id,
                "revision": 1,
                "status": "open",
                "stake": "100.00",
                "decimal_odds": "2.50",
                "funding": "freebet",
            }
        return {"bet_id": bet_id, "payout_difference": "0.00"}

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message()
    asyncio.run(real_bets.cb_bet_settle(_callback(f"bet:settle:{bet_id}", message), cfg, state))
    asyncio.run(real_bets.cb_bet_result(_callback("bet:result:void", message), cfg, state))
    assert state.data["expected_payout"] == "0.00"
    asyncio.run(real_bets.cb_expected_payout(_callback("bet:payout:expected", message), cfg, state))
    asyncio.run(real_bets.cb_bet_settled_time(_callback("bet:settled:now", message), cfg, state))
    asyncio.run(
        real_bets.cb_bet_settle_confirm(_callback("bet:settle_confirm", message), cfg, state)
    )
    assert requests[-1][0:2] == ("PATCH", f"bets/{bet_id}")
    assert requests[-1][2]["result"] == "void"
    assert requests[-1][2]["payout"] == "0.00"


def test_settlement_hint_uses_same_half_cent_rounding_as_api(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    state.data = {
        "bet_id": "12345678-1234-1234-1234-123456789abc",
        "bet": {"stake": "0.01", "decimal_odds": "2.50", "funding": "cash"},
    }
    message = _message()
    asyncio.run(real_bets.cb_bet_result(_callback("bet:result:win", message), cfg, state))
    assert state.data["expected_payout"] == "0.03"


def test_bet_journal_rejects_non_owner_or_group_chat() -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101, 202], "bets_owner_id": "101"}})
    group = _message()
    group.chat.type = "group"
    outsider = _message()
    outsider.from_user.id = 202
    assert real_bets._private_owner(group, cfg) is None
    assert real_bets._private_owner(outsider, cfg) is None


def test_owner_can_start_bet_from_calendar_match_without_prediction(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})

    async def control(_cfg, _owner, method, path, *, payload=None, **_kwargs):
        assert (method, path) == ("POST", "bet-contexts/manual")
        assert payload == {"tournament": "nhl", "match_id": "2026020084"}
        return {
            "context_id": "12345678-1234-1234-1234-123456789abc",
            "prediction": {"home_player": "WSH", "away_player": "SEA"},
        }

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message("/bet_add nhl 2026020084")
    asyncio.run(real_bets.cmd_bet_add(message, cfg))
    assert "Прогноза и Pinnacle-котировки нет" in message.answer.await_args.args[0]
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data.endswith(
        "12345678-1234-1234-1234-123456789abc"
    )


def test_manual_football_bet_uses_tournament_and_draw_choice(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    context_id = "12345678-1234-1234-1234-123456789abc"

    async def control(_cfg, _owner, method, path, *, payload=None, **_kwargs):
        if method == "POST":
            assert path == "bet-contexts/manual"
            assert payload == {"tournament": "epl", "match_id": "fixture-17"}
        return {
            "context_id": context_id,
            "prediction": {
                "tournament": "epl",
                "home_player": "Arsenal",
                "away_player": "Chelsea",
                "market_spec": "winner_1x2",
                "predictions": {},
                "available_outcomes": ["home_win", "draw", "away_win"],
            },
        }

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message("/bet_add epl fixture-17")
    asyncio.run(real_bets.cmd_bet_add(message, cfg))
    assert "Турнир: epl" in message.answer.await_args.args[0]
    assert "1X2, основное время" in message.answer.await_args.args[0]
    asyncio.run(real_bets.cb_new_bet(_callback(f"bet:new:{context_id}", message), cfg, state))
    buttons = message.answer.await_args.kwargs["reply_markup"].inline_keyboard
    assert [button[0].text for button in buttons] == [
        "Победа хозяев (основное время)",
        "Ничья (основное время)",
        "Победа гостей (основное время)",
    ]


def test_bet_report_shows_tournament_breakdown(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})

    async def control(_cfg, _owner, _method, _path, **_kwargs):
        return {
            "settled_count": 1,
            "open_count": 0,
            "cash_turnover": "100.00",
            "cash_pnl": "120.00",
            "cash_roi": "1.2000",
            "freebet_nominal": "0.00",
            "freebet_payout": "0.00",
            "total_cash_pnl": "120.00",
            "hit_rate": "1.0000",
            "by_tournament": {"epl": {"total_cash_pnl": "120.00"}},
        }

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message("/bet_report 2026-10")
    asyncio.run(real_bets.cmd_bet_report(message, cfg))
    assert "Турниры: epl — 120.00 ₽" in message.answer.await_args.args[0]


def test_season_bet_report_sends_chart_to_owner(monkeypatch) -> None:
    """Сезонная команда отдаёт общий PnL и PNG только владельцу."""
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})

    async def control(_cfg, _owner, _method, path, **_kwargs):
        assert path == "bets/season-summary"
        return {
            "tournament": "nhl",
            "start": "2026-09-01",
            "end": "2026-10-31",
            "settled_count": 0,
            "open_count": 0,
            "cash_turnover": "0.00",
            "cash_pnl": "0.00",
            "cash_roi": None,
            "freebet_nominal": "0.00",
            "freebet_payout": "0.00",
            "total_cash_pnl": "0.00",
            "hit_rate": None,
            "daily_pnl": [],
        }

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message("/bet_report season")
    asyncio.run(real_bets.cmd_bet_report(message, cfg))
    assert "Общий денежный PnL: 0.00 ₽" in message.answer.await_args.args[0]
    message.answer_photo.assert_awaited_once()


def test_bet_history_shows_tournament_for_each_bet(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})

    async def control(*_args, **_kwargs):
        return {
            "bets": [
                {
                    "bet_id": "12345678-1234-1234-1234-123456789abc",
                    "tournament": "epl",
                    "match_id": "fixture-17",
                    "market_spec": "winner_1x2",
                    "outcome": "draw",
                    "stake": "100.00",
                    "decimal_odds": "3.20",
                    "status": "open",
                }
            ]
        }

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message("/bet_history")
    asyncio.run(real_bets.cmd_bet_history(message, cfg))
    assert "epl · fixture-17" in message.answer.await_args.args[0]


def test_correction_command_uses_current_revision_and_stable_message_key(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    bet_id = "12345678-1234-1234-1234-123456789abc"
    calls: list[dict] = []

    async def control(_cfg, _owner, method, path, **kwargs):
        if method == "GET":
            return {"revision": 2}
        calls.append(kwargs)
        return {"revision": 3}

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message(f"/bet_correct {bet_id} payout 123,45")
    asyncio.run(real_bets.cmd_bet_correct(message, cfg))
    assert calls[0]["payload"] == {"expected_revision": 2, "payout": "123.45"}
    assert calls[0]["idempotency_key"] == "telegram:correct:101:42"


def test_successful_entry_removes_dialog_messages_but_keeps_prediction_card(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    context_id = "12345678-1234-1234-1234-123456789abc"
    bot = SimpleNamespace(delete_message=AsyncMock())
    next_id = 100

    async def control(_cfg, _owner, method, _path, **_kwargs):
        if method == "GET":
            return {
                "prediction": {
                    "home_player": "WSH",
                    "away_player": "SEA",
                    "market_spec": "winner_withOT",
                    "predictions": {"home_win": 0.6, "away_win": 0.4},
                }
            }
        return {"bet_id": "saved-bet"}

    def message(text: str = "") -> SimpleNamespace:
        nonlocal next_id
        next_id += 1
        current = _message(text)
        current.message_id = next_id
        current.bot = bot

        async def answer(*_args, **_kwargs):
            nonlocal next_id
            next_id += 1
            return SimpleNamespace(message_id=next_id)

        current.answer = AsyncMock(side_effect=answer)
        return current

    monkeypatch.setattr(real_bets, "_control_request", control)
    card = message()
    card_id = card.message_id
    awaitable = real_bets.cb_new_bet(_callback(f"bet:new:{context_id}", card), cfg, state)
    asyncio.run(awaitable)
    prompt_outcome = message()
    asyncio.run(real_bets.cb_bet_outcome(_callback("bet:outcome:0", prompt_outcome), cfg, state))
    prompt_funding = message()
    asyncio.run(real_bets.cb_bet_funding(_callback("bet:funding:cash", prompt_funding), cfg, state))
    asyncio.run(real_bets.msg_bet_stake(message("100"), cfg, state))
    asyncio.run(real_bets.msg_bet_odds(message("2,35"), cfg, state))
    prompt_time = message()
    asyncio.run(real_bets.cb_bet_placed(_callback("bet:placed:now", prompt_time), cfg, state))
    confirmation = message()
    asyncio.run(real_bets.cb_bet_confirm(_callback("bet:confirm", confirmation), cfg, state))
    deleted = {call.kwargs["message_id"] for call in bot.delete_message.await_args_list}
    assert card_id not in deleted
    assert {
        prompt_outcome.message_id,
        prompt_funding.message_id,
        prompt_time.message_id,
        confirmation.message_id,
    }.issubset(deleted)
    assert next_id in deleted  # последнее подтверждение «Ставка сохранена»
    assert len(deleted) >= 10


def test_bet_correct_help_shows_valid_examples() -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    message = _message("/bet_correct")
    asyncio.run(real_bets.cmd_bet_correct(message, cfg))
    help_text = message.answer.await_args.args[0]
    assert "/bet_correct ID_ставки stake 500,50" in help_text
    assert "/bet_correct ID_ставки placed_at 11.10.2026 19:30" in help_text
    assert "/bet_correct ID_ставки reopen" in help_text
    assert "cash" in help_text and "freebet" in help_text


def test_bet_correct_help_with_id_shows_its_market_outcomes(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    bet_id = "12345678-1234-1234-1234-123456789abc"

    async def control(*_args, **_kwargs):
        return {"market_spec": "winner_1x2"}

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message(f"/bet_correct {bet_id}")
    asyncio.run(real_bets.cmd_bet_correct(message, cfg))
    assert (
        "Для этой ставки исходы: home_win, draw или away_win" in message.answer.await_args.args[0]
    )


def test_invalid_football_outcome_correction_shows_allowed_values(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    bet_id = "12345678-1234-1234-1234-123456789abc"
    methods: list[str] = []

    async def control(_cfg, _owner, method, _path, **_kwargs):
        methods.append(method)
        if method == "GET":
            return {"revision": 1, "market_spec": "winner_1x2"}
        raise real_bets.ControlApiError(422)

    monkeypatch.setattr(real_bets, "_control_request", control)
    message = _message(f"/bet_correct {bet_id} outcome invalid")
    asyncio.run(real_bets.cmd_bet_correct(message, cfg))
    reply = message.answer.await_args.args[0]
    assert "home_win, draw или away_win" in reply
    assert f"/bet_correct {bet_id} outcome draw" in reply
    assert methods == ["GET"]


def test_failed_bet_save_keeps_dialog_for_retry(monkeypatch) -> None:
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101], "bets_owner_id": "101"}})
    state = FakeState()
    state.data = {
        "context_id": "12345678-1234-1234-1234-123456789abc",
        "outcome": "home_win",
        "funding": "cash",
        "stake": "100.00",
        "decimal_odds": "2.00",
        "placed_at": "2026-10-11T18:00:00+00:00",
        "request_id": "retry-key",
        "entry_message_ids": [20, 21],
    }
    message = _message()
    message.bot = SimpleNamespace(delete_message=AsyncMock())

    async def unavailable(*_args, **_kwargs):
        raise real_bets.ControlApiError("недоступно")

    monkeypatch.setattr(real_bets, "_control_request", unavailable)
    callback = _callback("bet:confirm", message)
    asyncio.run(real_bets.cb_bet_confirm(callback, cfg, state))
    assert state.data["request_id"] == "retry-key"
    assert state.data["entry_message_ids"] == [20, 21]
    message.bot.delete_message.assert_not_awaited()
    assert callback.answer.await_args.kwargs["show_alert"] is True
