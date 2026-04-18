"""Прогнозы и расписание через HTTP к FastAPI."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

router = Router(name="predict")


def _tournament_choices(_cfg: DictConfig) -> list[str]:
    raw = os.getenv("BOT_TOURNAMENTS", "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return ["nhl", "uel_kz_1", "uel_kz_2", "uel_cz", "lp_ru", "lp_eu", "lp_eu_a18", "lp_by"]


def _kb_tournaments(cfg: DictConfig, prefix: str):
    b = InlineKeyboardBuilder()
    for t in _tournament_choices(cfg):
        b.add(InlineKeyboardButton(text=t, callback_data=f"{prefix}:{t}"))
    b.adjust(2)
    return b.as_markup()


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    r = await client.get(url, timeout=60.0)
    r.raise_for_status()
    return r.json()


def _format_prediction_card(item: dict[str, Any]) -> str:
    mid = item.get("match_id", "")
    dt = item.get("match_datetime", "")
    hp = item.get("home_player", "")
    ap = item.get("away_player", "")
    pr = item.get("predictions") or {}
    if isinstance(pr, str):
        try:
            pr = json.loads(pr)
        except json.JSONDecodeError:
            pr = {}
    lines = [f"<b>{hp}</b> vs <b>{ap}</b>", f"id: <code>{mid}</code>", f"время: {dt}"]
    if isinstance(pr, dict):
        for k, v in pr.items():
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


@router.message(Command("predict"))
async def cmd_predict(message: Message, cfg: DictConfig) -> None:
    """Показать клавиатуру турниров → upcoming predictions."""
    await message.answer("Выберите турнир:", reply_markup=_kb_tournaments(cfg, "pred"))


@router.callback_query(F.data.startswith("pred:"))
async def cb_predict(cq: CallbackQuery, cfg: DictConfig) -> None:
    if cq.data is None or cq.message is None:
        return
    tournament = cq.data.split(":", 1)[1]
    base = str(cfg.bot.api_base_url).rstrip("/")
    url = f"{base}/predict/upcoming/{tournament}"
    async with httpx.AsyncClient() as client:
        try:
            data = await _fetch_json(client, url)
        except Exception as e:
            logger.exception("predict fetch failed")
            await cq.message.answer(f"Ошибка API: {e}")
            await cq.answer()
            return
    items = data.get("predictions") or []
    if not items:
        await cq.message.answer(f"Нет предсказаний для {tournament}")
        await cq.answer()
        return
    chunk = "\n\n---\n\n".join(_format_prediction_card(x) for x in items[:10])
    await cq.message.answer(chunk[:4000])
    await cq.answer()


@router.callback_query(F.data.startswith("up:"))
async def cb_upcoming(cq: CallbackQuery, cfg: DictConfig) -> None:
    if cq.data is None or cq.message is None:
        return
    tournament = cq.data.split(":", 1)[1]
    base = str(cfg.bot.api_base_url).rstrip("/")
    url = f"{base}/predict/upcoming/{tournament}"
    async with httpx.AsyncClient() as client:
        try:
            data = await _fetch_json(client, url)
        except Exception as e:
            await cq.message.answer(f"Ошибка API: {e}")
            await cq.answer()
            return
    items = data.get("predictions") or []
    text = "\n\n".join(
        f"{x.get('home_player')} — {x.get('away_player')} ({x.get('match_datetime')})"
        for x in (items[:20] if items else [])
    )
    await cq.message.answer(text or "Пусто")
    await cq.answer()


@router.message(Command("upcoming"))
async def cmd_upcoming(message: Message, cfg: DictConfig) -> None:
    """Расписание: аргумент турнира или клавиатура."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        tournament = parts[1].strip()
        base = str(cfg.bot.api_base_url).rstrip("/")
        url = f"{base}/predict/upcoming/{tournament}"
        async with httpx.AsyncClient() as client:
            try:
                data = await _fetch_json(client, url)
            except Exception as e:
                await message.answer(f"Ошибка API: {e}")
                return
        items = data.get("predictions") or []
        if not items:
            await message.answer("Пусто")
            return
        text = "\n\n".join(
            f"{x.get('home_player')} — {x.get('away_player')} ({x.get('match_datetime')})"
            for x in items[:20]
        )
        await message.answer(text[:4000])
        return
    await message.answer("Выберите турнир:", reply_markup=_kb_tournaments(cfg, "up"))
