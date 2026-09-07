"""Сборка ``Dispatcher`` и роутеров aiogram 3."""

from __future__ import annotations

import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from omegaconf import DictConfig

from sports_forecast.bot.handlers import admin, predict, start
from sports_forecast.bot.middleware import AllowedUsersMiddleware, InjectConfigMiddleware


def build_dispatcher(cfg: DictConfig, token: str) -> tuple[Bot, Dispatcher]:
    """Создать бота и диспетчер с зарегистрированными хендлерами.

    Args:
        cfg: Hydra-конфиг ``conf/bot.yaml`` (ветка ``bot``).
        token: ``BOT_TOKEN``.

    Returns:
        Пара ``(Bot, Dispatcher)``.
    """
    telegram_base_url = os.getenv("BOT_TELEGRAM_API_BASE_URL", "").strip()
    session = (
        AiohttpSession(api=TelegramAPIServer.from_base(telegram_base_url))
        if telegram_base_url
        else None
    )
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    allowed = {int(x) for x in (cfg.bot.get("allowed_user_ids") or []) if x is not None}
    if not allowed:
        raise ValueError("bot.allowed_user_ids пуст — задайте BOT_ALLOWED_USER_IDS")
    dp.update.middleware(InjectConfigMiddleware(cfg))
    dp.message.middleware(AllowedUsersMiddleware(allowed))
    dp.callback_query.middleware(AllowedUsersMiddleware(allowed))
    dp.include_router(start.router)
    dp.include_router(predict.router)
    dp.include_router(admin.router)
    dp["cfg"] = cfg
    dp["admin_ids"] = {int(x) for x in (cfg.bot.get("admin_user_ids") or []) if x is not None}
    return bot, dp
