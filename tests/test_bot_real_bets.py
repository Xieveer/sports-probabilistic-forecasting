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
    message = _message("/bet_add 2026020084")
    asyncio.run(real_bets.cmd_bet_add(message, cfg))
    assert "Прогноза и Pinnacle-котировки нет" in message.answer.await_args.args[0]
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data.endswith(
        "12345678-1234-1234-1234-123456789abc"
    )


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
