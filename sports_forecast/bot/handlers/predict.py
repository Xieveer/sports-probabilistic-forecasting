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
from omegaconf import DictConfig, OmegaConf

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


def _is_nhl_tournament(tournament: str) -> bool:
    """Турнир NHL: slug ``nhl``; ``nhl_train``/``nhl_*`` — только совместимость со старыми данными."""
    t = tournament.strip().lower()
    return t == "nhl" or t.startswith("nhl_")


def _upcoming_query_params(tournament: str, cfg: DictConfig) -> dict[str, str | bool]:
    """Параметры GET ``/predict/upcoming/{tournament}`` (R37.7: live + рынок OT для NHL)."""
    params: dict[str, str | bool] = {}
    if bool(OmegaConf.select(cfg, "bot.live_pinnacle", default=True)):
        params["live_pinnacle"] = True
    if _is_nhl_tournament(tournament):
        params["market"] = "winner_withOT"
        params["market_spec"] = "winner_withOT"
    return params


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | bool] | None = None,
) -> Any:
    r = await client.get(url, timeout=60.0, params=params or None)
    r.raise_for_status()
    return r.json()


def _bet_decision_ru(code: str | None) -> str:
    if not code:
        return "—"
    key = str(code).strip().lower()
    mapping = {
        "bet": "ставка",
        "no_bet": "нет ставки",
        "insufficient_data": "недостаточно данных",
    }
    return mapping.get(key, str(code))


def _format_live_lines(item: dict[str, Any]) -> list[str]:
    """Строки блока live Pinnacle / edge для ответа API (graceful при missing_api_key и т.д.)."""
    status = item.get("live_odds_status")
    if status in (None, "", "skipped_not_nhl", "skipped_unsupported_market", "disabled"):
        return []

    if status == "missing_api_key":
        return ["Live Pinnacle: на API не задан ODDS_API_KEY (edge недоступен)."]
    if status == "fetch_failed":
        return ["Live Pinnacle: ошибка The Odds API (edge недоступен)."]
    if status == "no_quote":
        return ["Live Pinnacle: линия не найдена (edge недоступен)."]

    ph = item.get("pinnacle_home_decimal")
    pa = item.get("pinnacle_away_decimal")
    edge = item.get("edge_home")
    bet = item.get("bet_decision_home")

    out: list[str] = []
    if ph is not None and pa is not None:
        out.append(f"Pinnacle (dec): home {float(ph):.2f} | away {float(pa):.2f}")
    elif ph is not None:
        out.append(f"Pinnacle home: {float(ph):.2f} (away — нет линии)")
    elif pa is not None:
        out.append(f"Pinnacle away: {float(pa):.2f} (home — нет линии)")
    else:
        out.append("Pinnacle: котировки недоступны")

    if edge is not None:
        out.append(f"Edge home: {float(edge):+.4f}")
    else:
        out.append("Edge home: —")

    out.append(f"Решение (home ML): {_bet_decision_ru(bet if isinstance(bet, str) else None)}")
    if status == "partial_quote":
        out.append("(частичная котировка)")
    return out


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
    live = _format_live_lines(item)
    if live:
        lines.append("")
        lines.extend(live)
    return "\n".join(lines)


def _format_upcoming_line(item: dict[str, Any]) -> str:
    """Одна строка расписания + при наличии — блок live/edge."""
    line1 = f"{item.get('home_player')} — {item.get('away_player')} ({item.get('match_datetime')})"
    live = _format_live_lines(item)
    if not live:
        return line1
    return line1 + "\n  " + "\n  ".join(live)


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
    params = _upcoming_query_params(tournament, cfg)
    async with httpx.AsyncClient() as client:
        try:
            data = await _fetch_json(client, url, params=params)
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
    params = _upcoming_query_params(tournament, cfg)
    async with httpx.AsyncClient() as client:
        try:
            data = await _fetch_json(client, url, params=params)
        except Exception as e:
            logger.exception("upcoming fetch failed")
            await cq.message.answer(f"Ошибка API: {e}")
            await cq.answer()
            return
    items = data.get("predictions") or []
    text = "\n\n".join(_format_upcoming_line(x) for x in (items[:20] if items else []))
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
        params = _upcoming_query_params(tournament, cfg)
        async with httpx.AsyncClient() as client:
            try:
                data = await _fetch_json(client, url, params=params)
            except Exception as e:
                logger.exception("upcoming command fetch failed")
                await message.answer(f"Ошибка API: {e}")
                return
        items = data.get("predictions") or []
        if not items:
            await message.answer("Пусто")
            return
        text = "\n\n".join(_format_upcoming_line(x) for x in items[:20])
        await message.answer(text[:4000])
        return
    await message.answer("Выберите турнир:", reply_markup=_kb_tournaments(cfg, "up"))
