"""Тесты middleware и разрешений бота."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from aiogram.types import CallbackQuery, Chat, Message, User

from sports_forecast.bot.middleware import AllowedUsersMiddleware


def _msg(uid: int) -> Message:
    return Message.model_construct(
        message_id=1,
        date=0,
        chat=Chat.model_construct(id=1, type="private"),
        from_user=User.model_construct(id=uid, is_bot=False, first_name="t"),
        text="/x",
    )


def test_allowed_users_middleware_blocks() -> None:
    async def _run() -> None:
        mw = AllowedUsersMiddleware({1})
        handler = AsyncMock(return_value="ok")
        msg = _msg(99)
        data: dict = {}
        res = await mw(handler, msg, data)
        assert res is None
        handler.assert_not_called()

    asyncio.run(_run())


def _cbq(uid: int) -> CallbackQuery:
    return CallbackQuery.model_construct(
        id="x",
        from_user=User.model_construct(id=uid, is_bot=False, first_name="t"),
        chat_instance="ci",
        data="d",
    )


def test_allowed_users_middleware_callback_blocks() -> None:
    async def _run() -> None:
        mw = AllowedUsersMiddleware({1})
        handler = AsyncMock(return_value="ok")
        cbq = _cbq(99)
        data: dict = {}
        res = await mw(handler, cbq, data)
        assert res is None
        handler.assert_not_called()

    asyncio.run(_run())


def test_allowed_users_middleware_passes() -> None:
    async def _run() -> None:
        mw = AllowedUsersMiddleware({42})
        handler = AsyncMock(return_value="ok")
        msg = _msg(42)
        data: dict = {}
        res = await mw(handler, msg, data)
        assert res == "ok"
        handler.assert_awaited_once()

    asyncio.run(_run())
