"""Прогнозы и расписание через HTTP к FastAPI."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
_MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

router = Router(name="predict")


class ScheduleState(StatesGroup):
    """Шаги запроса календаря турнира."""

    waiting_days = State()


# Лёгкий операционный путь (R41): только HTTP GET к витрине + ``live_pinnacle`` на стороне API.
# Никаких вызовов Airflow/source_refresh/features.
LIGHT_PATH_EDGE_HTML = (
    "🔄 <b>Лёгкий путь · котировки/edge</b>\n"
    "Актуальные коэффициенты через API (<code>/predict/upcoming</code>, "
    "<code>live_pinnacle</code>); вероятности из витрины <b>без пересчёта</b>.\n"
    "Не путать с админским <code>/refresh</code> — полный пайплайн данных.\n\n"
)


def _predict_upcoming_url(base_api: str, tournament: str) -> str:
    """Публичный URL ``GET /predict/upcoming/{tournament}`` (лёгкий путь без Airflow)."""
    root = base_api.rstrip("/")
    return f"{root}/predict/upcoming/{tournament.strip()}"


async def fetch_predict_upcoming(
    client: httpx.AsyncClient,
    *,
    cfg: DictConfig,
    tournament: str,
) -> dict[str, Any]:
    """Загрузить предстоящие матчи через тот же контракт, что и Telegram/digest enrichment (GET)."""
    base = str(cfg.bot.api_base_url).rstrip("/")
    url = _predict_upcoming_url(base, tournament)
    params = _upcoming_query_params(tournament, cfg)
    data = await _fetch_json(client, url, params=params)
    return data if isinstance(data, dict) else {"predictions": []}


async def fetch_schedule(
    client: httpx.AsyncClient,
    *,
    cfg: DictConfig,
    tournament: str,
    days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Загрузить календарь до конца выбранного дня МСК."""
    base = str(cfg.bot.api_base_url).rstrip("/")
    window_start, deadline = _schedule_window(days, now=now)
    params = _upcoming_query_params(tournament, cfg)
    params["hours"] = _schedule_window_hours(days, now=window_start)
    data = await _fetch_json(client, _predict_upcoming_url(base, tournament), params=params)
    if not isinstance(data, dict):
        return {"predictions": []}
    items = data.get("predictions") or []
    return {
        **data,
        "predictions": [
            item
            for item in items
            if isinstance(item, dict) and _is_in_schedule_window(item, window_start, deadline)
        ],
    }


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


def _kb_schedule_tournaments():
    """Вернуть доступные в первом пилоте турниры расписания."""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="NHL", callback_data="schedule:nhl"))
    return b.as_markup()


def _is_nhl_tournament(tournament: str) -> bool:
    """Турнир NHL: slug ``nhl``; ``nhl_train``/``nhl_*`` — только совместимость со старыми данными."""
    t = tournament.strip().lower()
    return t == "nhl" or t.startswith("nhl_")


def _upcoming_query_params(tournament: str, cfg: DictConfig) -> dict[str, str | bool | int]:
    """Параметры GET ``/predict/upcoming/{tournament}`` (R37.7: live + рынок OT для NHL)."""
    params: dict[str, str | bool | int] = {}
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
    params: dict[str, str | bool | int] | None = None,
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

    edge_a = item.get("edge_away")
    if edge_a is not None:
        out.append(f"Edge away: {float(edge_a):+.4f}")
    else:
        out.append("Edge away: —")

    bet_a = item.get("bet_decision_away")
    out.append(f"Решение (home ML): {_bet_decision_ru(bet if isinstance(bet, str) else None)}")
    out.append(f"Решение (away ML): {_bet_decision_ru(bet_a if isinstance(bet_a, str) else None)}")
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


def _schedule_window(days: int, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Вернуть точные UTC-границы периода календаря."""
    current = (now or datetime.now(UTC)).astimezone(MOSCOW_TZ)
    deadline = current.replace(hour=23, minute=59, second=59, microsecond=999999) + timedelta(
        days=days
    )
    return current.astimezone(UTC), deadline.astimezone(UTC)


def _schedule_window_hours(days: int, *, now: datetime | None = None) -> int:
    """Вернуть округлённый вверх API-горизонт, сохраняя точную границу в фильтре."""
    start, deadline = _schedule_window(days, now=now)
    return max(1, ceil((deadline - start).total_seconds() / 3600))


def _parse_schedule_datetime(value: object) -> datetime | None:
    """Прочитать время API: SQLite wall-time без offset считается UTC."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _is_in_schedule_window(item: dict[str, Any], start: datetime, deadline: datetime) -> bool:
    """Проверить точную границу, которую часовое API-окно выразить не может."""
    moment = _parse_schedule_datetime(item.get("match_datetime"))
    return moment is not None and start <= moment <= deadline


def _schedule_decimal(value: Any) -> str:
    """Отформатировать коэффициент, не скрывая отсутствующее отдельное поле."""
    return f"{float(value):.2f}" if value is not None else "нет данных"


def _schedule_value(value: Any) -> str:
    """Отформатировать value, не скрывая отсутствующее отдельное поле."""
    return f"{float(value):+.4f}" if value is not None else "нет данных"


def _schedule_decision(value: object) -> str:
    """Вернуть русское решение или явный маркер отсутствующих данных."""
    return _bet_decision_ru(value) if isinstance(value, str) else "нет данных"


def _format_schedule(items: list[dict[str, Any]]) -> str:
    """Сгруппировать будущие матчи по календарным дням МСК."""
    groups: dict[str, list[str]] = {}
    for item in items:
        utc_moment = _parse_schedule_datetime(item.get("match_datetime"))
        if utc_moment is None:
            continue
        moment = utc_moment.astimezone(MOSCOW_TZ)
        prediction = item.get("predictions")
        prediction_text = (
            ", ".join(f"{key}: {value}" for key, value in prediction.items())
            if isinstance(prediction, dict) and prediction
            else "нет данных"
        )
        date_label = f"{moment.day} {_MONTHS_RU[moment.month - 1]}"
        card = (
            f"{moment:%H:%M} МСК  {item.get('home_player')} — {item.get('away_player')}\n"
            f"Прогноз: {prediction_text}\n"
            f"Коэффициенты: home {_schedule_decimal(item.get('pinnacle_home_decimal'))} | "
            f"away {_schedule_decimal(item.get('pinnacle_away_decimal'))}\n"
            f"Value: home {_schedule_value(item.get('edge_home'))} | "
            f"away {_schedule_value(item.get('edge_away'))}\n"
            f"Решение: home {_schedule_decision(item.get('bet_decision_home'))} | "
            f"away {_schedule_decision(item.get('bet_decision_away'))}"
        )
        groups.setdefault(date_label, []).append(card)
    return "\n\n".join(
        f"🏒 NHL — {date}\n\n" + "\n\n".join(cards) for date, cards in groups.items()
    )


def _split_schedule_messages(items: list[dict[str, Any]], *, limit: int = 4000) -> list[str]:
    """Разбить расписание на сообщения Telegram, не теряя матчей из-за лимита."""
    text = _format_schedule(items)
    if not text:
        return []
    header = ""
    messages: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        if block.startswith("🏒 NHL — "):
            if current:
                messages.append(current)
                current = ""
            header = block
            continue
        card = f"{header}\n\n{block}"
        if len(card) > limit:
            if current:
                messages.append(current)
                current = ""
            messages.extend(card[offset : offset + limit] for offset in range(0, len(card), limit))
        elif current and len(current) + 2 + len(block) > limit:
            messages.append(current)
            current = card
        else:
            current = f"{current}\n\n{block}" if current else card
    if current:
        messages.append(current)
    return messages


@router.message(Command("predict"))
async def cmd_predict(message: Message, cfg: DictConfig) -> None:
    """Показать клавиатуру турниров → upcoming predictions."""
    await message.answer("Выберите турнир:", reply_markup=_kb_tournaments(cfg, "pred"))


@router.callback_query(F.data.startswith("pred:"))
async def cb_predict(cq: CallbackQuery, cfg: DictConfig) -> None:
    if cq.data is None or cq.message is None:
        return
    tournament = cq.data.split(":", 1)[1]
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_predict_upcoming(client, cfg=cfg, tournament=tournament)
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
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_predict_upcoming(client, cfg=cfg, tournament=tournament)
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
async def cmd_upcoming(message: Message) -> None:
    """Начать сценарий выбора турнира и календарного горизонта."""
    await message.answer("Выберите турнир:", reply_markup=_kb_schedule_tournaments())


@router.callback_query(F.data.startswith("schedule:"))
async def cb_schedule_tournament(cq: CallbackQuery, state: FSMContext) -> None:
    """Сохранить турнир и запросить календарный горизонт."""
    if cq.data is None or cq.message is None:
        return
    tournament = cq.data.split(":", 1)[1]
    await state.update_data(schedule_tournament=tournament)
    await state.set_state(ScheduleState.waiting_days)
    await cq.message.answer("Введите число дней от 0 до 30 (0 — до конца сегодня):")
    await cq.answer()


@router.message(ScheduleState.waiting_days)
async def schedule_days(message: Message, state: FSMContext, cfg: DictConfig) -> None:
    """Вернуть календарь выбранного турнира на заданный период."""
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число от 0 до 30.")
        return
    if not 0 <= days <= 30:
        await message.answer("Введите число от 0 до 30.")
        return
    tournament = str((await state.get_data()).get("schedule_tournament", "nhl"))
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_schedule(client, cfg=cfg, tournament=tournament, days=days)
        except (httpx.HTTPError, ValueError):
            logger.exception("schedule fetch failed")
            await message.answer("Расписание временно недоступно.")
            return
    await state.clear()
    messages = _split_schedule_messages(data.get("predictions") or [])
    if not messages:
        await message.answer("В выбранном периоде будущих матчей нет.")
        return
    for text in messages:
        await message.answer(text)


@router.message(Command("edge"))
async def cmd_edge(message: Message, cfg: DictConfig) -> None:
    """Повторно запросить live-котировки/edge через API без Airflow (R41 лёгкий путь)."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        tournament = parts[1].strip()
        async with httpx.AsyncClient() as client:
            try:
                data = await fetch_predict_upcoming(client, cfg=cfg, tournament=tournament)
            except Exception as e:
                logger.exception("edge command fetch failed")
                await message.answer(f"Ошибка API: {e}")
                return
        items = data.get("predictions") or []
        if not items:
            await message.answer(LIGHT_PATH_EDGE_HTML + "Пусто")
            return
        text = "\n\n".join(_format_prediction_card(x) for x in items[:10])
        await message.answer(LIGHT_PATH_EDGE_HTML + text[:3800])
        return
    await message.answer(
        LIGHT_PATH_EDGE_HTML + "Выберите турнир:",
        reply_markup=_kb_tournaments(cfg, "edge"),
    )


@router.callback_query(F.data.startswith("edge:"))
async def cb_edge(cq: CallbackQuery, cfg: DictConfig) -> None:
    """Кнопка «обновить edge» для whitelist-пользователя (только GET /predict/upcoming/*)."""
    if cq.data is None or cq.message is None:
        return
    tournament = cq.data.split(":", 1)[1]
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_predict_upcoming(client, cfg=cfg, tournament=tournament)
        except Exception as e:
            logger.exception("edge callback fetch failed")
            await cq.message.answer(f"Ошибка API: {e}")
            await cq.answer()
            return
    items = data.get("predictions") or []
    if not items:
        await cq.message.answer(LIGHT_PATH_EDGE_HTML + f"Нет предсказаний для {tournament}")
        await cq.answer()
        return
    chunk = "\n\n---\n\n".join(_format_prediction_card(x) for x in items[:10])
    await cq.message.answer(LIGHT_PATH_EDGE_HTML + chunk[:3800])
    await cq.answer()
