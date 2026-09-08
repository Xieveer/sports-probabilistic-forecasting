"""Регистрация меню команд Telegram с существующими границами доступа."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from aiogram.types import BotCommandScopeChat
from omegaconf import OmegaConf

from sports_forecast.bot.dispatcher import register_commands


def test_register_commands_sets_public_and_admin_scoped_menus() -> None:
    """Админский scope дополняет public menu, не открывая admin commands всем."""
    bot = AsyncMock()
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [7, 9]}})

    asyncio.run(register_commands(bot, cfg))

    calls = bot.set_my_commands.await_args_list
    assert len(calls) == 3
    public = [command.command for command in calls[0].args[0]]
    assert public == ["start", "help", "predict", "upcoming", "edge"]
    for call, user_id in zip(calls[1:], (7, 9), strict=True):
        assert [command.command for command in call.args[0]] == [
            "start",
            "help",
            "predict",
            "upcoming",
            "edge",
            "status",
            "refresh",
            "models",
        ]
        assert isinstance(call.kwargs["scope"], BotCommandScopeChat)
        assert call.kwargs["scope"].chat_id == user_id
