"""Прогнозы и расписание через HTTP к FastAPI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
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

from sports_forecast.bot.handlers.real_bets import card_context_button, create_card_context
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
_SCHEDULE_DIVIDER = "—————————————————————————————"
_MAX_SCHEDULE_PARTICIPANT_LENGTH = 128

router = Router(name="predict")


class ScheduleState(StatesGroup):
    """Шаги запроса календаря турнира."""

    waiting_period = State()


SCHEDULE_PERIODS = ("today", "tomorrow", "3", "7", "14", "30")
SCHEDULE_PAGE_SIZE = 50
_PERIOD_LABELS = {
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "3": "3 дня",
    "7": "7 дней",
    "14": "14 дней",
    "30": "30 дней",
}


def _predict_upcoming_url(base_api: str, tournament: str) -> str:
    """Публичный URL ``GET /predict/upcoming/{tournament}`` (лёгкий путь без Airflow)."""
    root = base_api.rstrip("/")
    return f"{root}/predict/upcoming/{tournament.strip()}"


async def fetch_predict_upcoming(
    client: httpx.AsyncClient,
    *,
    cfg: DictConfig,
    tournament: str,
    period: str | None = None,
) -> dict[str, Any]:
    """Загрузить предстоящие матчи через тот же контракт, что и Telegram/digest enrichment (GET)."""
    base = str(cfg.bot.api_base_url).rstrip("/")
    url = _predict_upcoming_url(base, tournament)
    params = _upcoming_query_params(tournament, cfg, period=period)
    data = await _fetch_json(client, url, params=params)
    return data if isinstance(data, dict) else {"predictions": []}


async def fetch_schedule(
    client: httpx.AsyncClient,
    *,
    cfg: DictConfig,
    tournament: str,
    period: str,
) -> dict[str, Any]:
    """Загрузить страницу независимого source-календаря."""
    if period not in SCHEDULE_PERIODS:
        raise ValueError("Недопустимый период календаря")
    base = str(cfg.bot.api_base_url).rstrip("/")
    url = f"{base}/calendar/{tournament.strip()}"
    data = await _fetch_json(
        client,
        url,
        params={"period": period, "limit": SCHEDULE_PAGE_SIZE, "offset": 0},
    )
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("Некорректный ответ календаря")
    return data


def _kb_schedule_tournaments():
    """Вернуть доступные в первом пилоте турниры расписания."""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="NHL", callback_data="schedule:nhl"))
    return b.as_markup()


def _kb_schedule_periods():
    """Клавиатура разрешённых календарных периодов."""
    builder = InlineKeyboardBuilder()
    for period in SCHEDULE_PERIODS:
        builder.button(text=_PERIOD_LABELS[period], callback_data=f"period:{period}")
    builder.adjust(2)
    return builder.as_markup()


def _kb_predict_periods():
    """Кнопки периода для прогнозов с теми же bookmaker-day границами."""
    builder = InlineKeyboardBuilder()
    for period in SCHEDULE_PERIODS:
        builder.button(text=_PERIOD_LABELS[period], callback_data=f"predict_period:{period}:0")
    builder.adjust(2)
    return builder.as_markup()


def _is_nhl_tournament(tournament: str) -> bool:
    """Турнир NHL: slug ``nhl``; ``nhl_train``/``nhl_*`` — только совместимость со старыми данными."""
    t = tournament.strip().lower()
    return t == "nhl" or t.startswith("nhl_")


def _upcoming_query_params(
    tournament: str, cfg: DictConfig, *, period: str | None = None
) -> dict[str, str | bool | int]:
    """Параметры GET ``/predict/upcoming/{tournament}`` (R37.7: live + рынок OT для NHL)."""
    params: dict[str, str | bool | int] = {}
    if bool(OmegaConf.select(cfg, "bot.live_pinnacle", default=True)):
        params["live_pinnacle"] = True
    if _is_nhl_tournament(tournament):
        params["market"] = "winner_withOT"
        params["market_spec"] = "winner_withOT"
    if period is not None:
        if period not in SCHEDULE_PERIODS:
            raise ValueError("Недопустимый период прогнозов")
        params["period"] = period
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
    mid = escape(str(item.get("match_id") or "—")[:64])
    dt = _parse_schedule_datetime(item.get("match_datetime"))
    time_label = dt.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК") if dt else "—"
    hp = escape(str(item.get("home_player") or "—")[:128])
    ap = escape(str(item.get("away_player") or "—")[:128])
    pr = item.get("predictions") or {}
    if isinstance(pr, str):
        try:
            pr = json.loads(pr)
        except json.JSONDecodeError:
            pr = {}
    probabilities = pr if isinstance(pr, dict) else {}
    home = _finite_number(probabilities.get("home_win"))
    away = _finite_number(probabilities.get("away_win"))
    market_spec = str(item.get("market_spec") or item.get("market") or "winner")[:64]
    market_label = "winner with OT" if market_spec == "winner_withOT" else escape(market_spec)
    lines = [
        f"<b>{hp} — {ap}</b>",
        f"Время: {time_label}",
        f"ID: <code>{mid}</code>",
        f"{market_label}: {_pair(home, away, 3)}",
    ]
    price_home = _finite_number(item.get("pinnacle_home_decimal"))
    price_away = _finite_number(item.get("pinnacle_away_decimal"))
    edge_home = _finite_number(item.get("edge_home"))
    edge_away = _finite_number(item.get("edge_away"))
    ev_home = home * price_home - 1 if home is not None and price_home is not None else None
    ev_away = away * price_away - 1 if away is not None and price_away is not None else None
    lines.extend(
        [
            f"Pinnacle: {_pair(price_home, price_away, 2)}",
            f"Edge: {_pair(edge_home, edge_away, 4, signed=True)}",
            f"EV: {_pair(ev_home, ev_away, 4, signed=True)}",
        ]
    )
    recommendations = item.get("recommendations")
    if isinstance(recommendations, list):
        for recommendation in recommendations[:4]:
            if not isinstance(recommendation, dict):
                continue
            rec_market = str(recommendation.get("market_spec") or "—")[:32]
            rec_outcome = str(recommendation.get("outcome") or "—")[:32]
            rec_market_label = (
                "winner with OT" if rec_market == "winner_withOT" else rec_market.replace("_", " ")
            )
            if rec_market == "winner_withOT" and rec_outcome in {"home_win", "away_win"}:
                rec_outcome_label = f"{rec_outcome.split('_')[0]} win with OT"
            else:
                rec_outcome_label = rec_outcome.replace("_", " ")
            lines.append(f"Решение · {escape(rec_market_label)}: {escape(rec_outcome_label)}")
        if not any(line.startswith("Решение · ") for line in lines):
            lines.append("Решение: нет рекомендации")
    else:
        selected = [
            side
            for side, key in (("home", "bet_decision_home"), ("away", "bet_decision_away"))
            if item.get(key) == "bet"
        ]
        outcome_suffix = " win with OT" if market_spec == "winner_withOT" else " win"
        decision = (
            ", ".join(f"{side}{outcome_suffix}" for side in selected)
            if selected
            else "нет рекомендации"
        )
        lines.append(f"Решение: {decision}")
    return "\n".join(lines)


def _finite_number(value: object) -> float | None:
    """Принять только конечное число для пользовательской карточки."""
    try:
        number = float(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
    return (
        number if number is not None and number == number and abs(number) != float("inf") else None
    )


def _pair(home: float | None, away: float | None, digits: int, *, signed: bool = False) -> str:
    """Показать значения в постоянном порядке home | away."""
    spec = f"{'+' if signed else ''}.{digits}f"
    return " | ".join(format(value, spec) if value is not None else "—" for value in (home, away))


def _format_upcoming_line(item: dict[str, Any]) -> str:
    """Одна строка расписания + при наличии — блок live/edge."""
    line1 = f"{item.get('home_player')} — {item.get('away_player')} ({item.get('match_datetime')})"
    live = _format_live_lines(item)
    if not live:
        return line1
    return line1 + "\n  " + "\n  ".join(live)


def _parse_schedule_datetime(value: object) -> datetime | None:
    """Прочитать время календаря; SQLite wall-time считается UTC."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment).astimezone(UTC)


def _coverage_label(status: object) -> str:
    """Объяснить пользователю полноту source-календаря."""
    return {
        "complete": "календарь актуален",
        "confirmed_empty": "пустое окно подтверждено источником",
        "incomplete": "покрытие календаря неполное",
        "stale": "данные календаря устарели",
        "unavailable": "последнее обновление календаря завершилось ошибкой",
        "unknown": "полнота календаря ещё не проверена",
    }.get(str(status), "состояние календаря неизвестно")


def _readiness_label(status: object) -> str:
    return {
        "current": "актуален",
        "changed": "изменён",
        "postponed": "перенесён",
        "cancelled": "отменён",
        "started": "начался",
        "finished": "завершён",
        "needs_review": "требует проверки",
        "ready": "готово",
        "partial": "частично готово",
        "pending": "ожидает",
        "waiting": "ожидает",
        "missing": "нет данных",
        "stale": "устарело",
        "failed": "ошибка",
        "error": "ошибка",
        "unavailable": "недоступно",
    }.get(str(status), "неизвестно")


def _calendar_cards(items: list[dict[str, Any]], *, participant_limit: int) -> dict[str, list[str]]:
    """Подготовить ограниченные по длине карточки без разрезания HTML-сущностей."""
    groups: dict[str, list[str]] = {}
    for item in items:
        utc_moment = _parse_schedule_datetime(item.get("scheduled_at"))
        if utc_moment is None:
            continue
        moment = utc_moment.astimezone(MOSCOW_TZ)
        date_label = f"{moment.day} {_MONTHS_RU[moment.month - 1]}"
        prediction = item.get("prediction_readiness") or {}
        odds = item.get("odds_readiness") or {}
        aggregate = item.get("readiness") or {}
        status = item.get("status")
        home = str(item.get("home_participant") or "—")
        away = str(item.get("away_participant") or "—")
        if len(home) > participant_limit:
            home = home[: participant_limit - 1] + "…"
        if len(away) > participant_limit:
            away = away[: participant_limit - 1] + "…"
        calendar = (
            "перенесён"
            if status == "postponed"
            else (
                "отменён"
                if status == "cancelled"
                else _readiness_label(item.get("calendar_readiness"))
            )
        )
        card = (
            f"{moment:%H:%M} МСК  {escape(home)} — {escape(away)}\n"
            f"Календарь: {calendar}\n"
            f"Прогноз: {_readiness_label(prediction.get('status'))}\n"
            f"Коэффициенты: {_readiness_label(odds.get('status'))}\n"
            f"Готовность: {_readiness_label(aggregate.get('status'))}"
        )
        groups.setdefault(date_label, []).append(card)
    return groups


def _format_calendar(items: list[dict[str, Any]]) -> str:
    """Сгруппировать calendar events по календарным дням МСК."""
    groups = _calendar_cards(items, participant_limit=_MAX_SCHEDULE_PARTICIPANT_LENGTH)
    return "\n\n".join(
        f"🏒 NHL — {date}\n{_SCHEDULE_DIVIDER}\n" + f"\n{_SCHEDULE_DIVIDER}\n".join(cards)
        for date, cards in groups.items()
    )


def _telegram_text_length(text: str) -> int:
    """Оценить длину сообщения в единицах UTF-16, которые использует Telegram."""
    return len(text.encode("utf-16-le")) // 2


def _split_schedule_messages(items: list[dict[str, Any]], *, limit: int = 4000) -> list[str]:
    """Разбить страницу на сообщения по карточкам в бюджете UTF-16 Telegram."""
    participant_limit = max(1, min(_MAX_SCHEDULE_PARTICIPANT_LENGTH, (limit - 512) // 10))
    groups = _calendar_cards(items, participant_limit=participant_limit)
    messages: list[str] = []
    for date, cards in groups.items():
        header = f"🏒 NHL — {date}\n{_SCHEDULE_DIVIDER}"
        current = header
        for block in cards:
            card = f"{header}\n{_SCHEDULE_DIVIDER}\n{block}"
            candidate = f"{current}\n{_SCHEDULE_DIVIDER}\n{block}"
            if current != header and _telegram_text_length(candidate) > limit:
                messages.append(current)
                current = card
            else:
                current = candidate
        if current != header:
            messages.append(current)
    return messages


@router.message(Command("predict"))
async def cmd_predict(message: Message) -> None:
    """Выбрать период прогнозов NHL по букмекерским суткам."""
    await message.answer(
        "Выберите период (сутки 08:00–08:00 МСК):", reply_markup=_kb_predict_periods()
    )


@router.callback_query(F.data.startswith("predict_period:"))
async def cb_predict_period(cq: CallbackQuery, cfg: DictConfig) -> None:
    if cq.data is None or cq.message is None:
        return
    parts = cq.data.split(":")
    if len(parts) != 3 or parts[1] not in SCHEDULE_PERIODS or not parts[2].isdigit():
        await cq.answer("Период недоступен.", show_alert=True)
        return
    period, offset = parts[1], int(parts[2])
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_predict_upcoming(client, cfg=cfg, tournament="nhl", period=period)
        except Exception:
            logger.exception("predict fetch failed")
            await cq.message.answer("Прогнозы временно недоступны.")
            await cq.answer()
            return
    items = data.get("predictions") or []
    if not items:
        await cq.message.answer("Нет прогнозов за выбранный период.")
        await cq.answer()
        return
    for item in items[offset : offset + 10]:
        owner_id = getattr(getattr(cq, "from_user", None), "id", None)
        chat = getattr(cq.message, "chat", None)
        admins = {
            int(value) for value in (cfg.bot.get("admin_user_ids") or []) if value is not None
        }
        configured_owner = str(cfg.bot.get("bets_owner_id") or "").strip()
        if (
            configured_owner.isdigit()
            and owner_id == int(configured_owner)
            and owner_id in admins
            and getattr(chat, "type", None) == "private"
        ):
            try:
                context = await create_card_context(cfg, int(owner_id), item)
            except Exception:
                logger.exception("bet card context failed")
                await cq.message.answer(
                    _format_prediction_card(item) + "\nЖурнал ставок временно недоступен."
                )
                continue
            await cq.message.answer(
                _format_prediction_card(context["prediction"]),
                reply_markup=card_context_button(str(context["context_id"])),
            )
        else:
            await cq.message.answer(_format_prediction_card(item))
    if offset + 10 < len(items):
        builder = InlineKeyboardBuilder()
        builder.button(
            text="Следующие прогнозы", callback_data=f"predict_period:{period}:{offset + 10}"
        )
        await cq.message.answer(
            f"Показано {offset + 10} из {len(items)}.", reply_markup=builder.as_markup()
        )
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
    """Сохранить турнир и показать стандартные периоды."""
    if cq.data is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    tournament = cq.data.split(":", 1)[1]
    await state.update_data(schedule_tournament=tournament)
    await state.set_state(ScheduleState.waiting_period)
    await cq.message.answer(
        "Выберите период букмекерских суток (08:00–08:00 МСК):", reply_markup=_kb_schedule_periods()
    )
    await cq.answer()


async def _send_schedule(message: Message, state: FSMContext, cfg: DictConfig, period: str) -> None:
    """Получить календарь и показать покрытие со страницей событий."""
    if period not in SCHEDULE_PERIODS:
        await message.answer("Этот период календаря не поддерживается.")
        return
    tournament = str((await state.get_data()).get("schedule_tournament", "nhl"))
    async with httpx.AsyncClient() as client:
        try:
            data = await fetch_schedule(client, cfg=cfg, tournament=tournament, period=period)
        except (httpx.HTTPError, ValueError):
            logger.exception("schedule fetch failed")
            await message.answer("Расписание временно недоступно.")
            return
    await state.clear()
    events = [item for item in data["events"] if isinstance(item, dict)]
    total = int(data.get("total") or 0)
    coverage = data.get("coverage") or {}
    shown = len(events)
    header = f"🏒 NHL · {_PERIOD_LABELS[period]}\n{_coverage_label(coverage.get('status'))}."
    if total:
        header += f" Показано {shown} из {total}."
    if total > shown:
        header += f"\nОстальные события не показаны: лимит страницы {SCHEDULE_PAGE_SIZE}."
    messages = _split_schedule_messages(events)
    if not messages:
        if coverage.get("status") == "confirmed_empty":
            header += " Матчей в этом периоде нет."
        elif coverage.get("status") in {"incomplete", "stale", "unavailable", "unknown"}:
            header += " Список матчей может быть неполным."
        else:
            header += " Матчей в этом периоде нет."
        await message.answer(header)
        return
    await message.answer(header)
    for text in messages:
        await message.answer(text)


@router.callback_query(F.data.startswith("period:"))
async def cb_schedule_period(cq: CallbackQuery, state: FSMContext, cfg: DictConfig) -> None:
    """Показать выбранный период source-календаря."""
    if cq.data is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    await _send_schedule(cq.message, state, cfg, cq.data.split(":", 1)[1])
    await cq.answer()
