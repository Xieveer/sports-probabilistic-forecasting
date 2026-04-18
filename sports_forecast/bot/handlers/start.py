"""Команды /start и /help."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Приветствие."""
    await message.answer(
        "Привет! Я бот прогнозов Sports Probabilistic Forecasting.\n\n"
        "Команды:\n"
        "/predict — ближайшие матчи с вероятностями\n"
        "/upcoming [турнир] — расписание из API\n"
        "/help — справка\n"
        "Админ: /status, /refresh, /models"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Краткая справка."""
    await cmd_start(message)
