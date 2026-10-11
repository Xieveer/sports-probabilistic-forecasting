"""Команды /start и /help."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from omegaconf import DictConfig


router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message, cfg: DictConfig | None = None) -> None:
    """Приветствие."""
    user = getattr(message, "from_user", None)
    user_id = user.id if user else 0
    admin_ids = (
        {int(value) for value in (cfg.bot.get("admin_user_ids") or []) if value is not None}
        if cfg is not None
        else set()
    )
    admin_help = (
        "Админ: /status, /cycle, /cycle_time HH:MM, /cycle_interval N, "
        "/cycle_history, /refresh (ручной Data Cycle)"
        if user_id in admin_ids
        else ""
    )
    bets_owner_id = str(cfg.bot.get("bets_owner_id") or "").strip() if cfg is not None else ""
    if bets_owner_id == str(user_id) and user_id in admin_ids:
        admin_help += (
            "; ставки: /bets, /bet_add ID_матча, /bet_history, /bet_report ГГГГ-ММ, "
            "/bet_correct, /bet_audit, /bet_cancel"
        )
    await message.answer(
        "Привет! Я бот прогнозов Sports Probabilistic Forecasting.\n\n"
        "Команды:\n"
        "/predict — ближайшие матчи с вероятностями\n"
        "/upcoming — календарь NHL: сегодня, завтра, 3/7/14/30 дней\n"
        "/help — справка\n"
        f"{admin_help}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, cfg: DictConfig | None = None) -> None:
    """Краткая справка."""
    await cmd_start(message, cfg)
