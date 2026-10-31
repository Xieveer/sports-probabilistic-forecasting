"""Ручная запись и расчёт одиночных ставок владельца в Telegram."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from omegaconf import DictConfig

from sports_forecast.betting.real_bets import MARKET_OUTCOMES, Funding, Result, expected_payout
from sports_forecast.bot.bet_chart import render_season_pnl_chart
from sports_forecast.bot.handlers.admin import ControlApiError, _control_request
from sports_forecast.utils.log_config import get_logger


router = Router(name="real_bets")
_MOSCOW = ZoneInfo("Europe/Moscow")
logger = get_logger(__name__)
_CORRECTION_HELP = (
    "Скопируйте ID из /bet_history и подставьте его вместо ID_ставки.\n"
    "Шаблон: /bet_correct ID_ставки поле значение\n"
    "Примеры:\n"
    "/bet_correct ID_ставки stake 500,50\n"
    "/bet_correct ID_ставки payout 1176,18\n"
    "/bet_correct ID_ставки odds 2,35\n"
    "/bet_correct ID_ставки funding freebet\n"
    "/bet_correct ID_ставки outcome home_win\n"
    "/bet_correct ID_ставки outcome draw\n"
    "/bet_correct ID_ставки result win\n"
    "/bet_correct ID_ставки placed_at 11.10.2026 19:30\n"
    "/bet_correct ID_ставки settled_at 12.10.2026 00:15\n"
    "/bet_correct ID_ставки cancel Ошибочно записана дважды\n"
    "/bet_correct ID_ставки reopen\n"
    "Значения funding: cash или freebet; result: win, loss или void. "
    "Для winner_withOT: home_win/away_win; для winner_1x2: home_win/draw/away_win. "
    "Время указывайте в МСК. Для result у открытой ставки также нужны выплата "
    "и время расчёта; удобнее использовать /bets."
)


async def _entry_answer(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    remember_incoming: bool = True,
    **kwargs: Any,
) -> None:
    """Отправить шаг записи и запомнить его вместе с ответом владельца."""
    data = await state.get_data()
    ids = list(data.get("entry_message_ids") or [])
    incoming_id = getattr(message, "message_id", None)
    if remember_incoming and isinstance(incoming_id, int) and incoming_id not in ids:
        ids.append(incoming_id)
    sent = await message.answer(text, **kwargs)
    sent_id = getattr(sent, "message_id", None)
    if isinstance(sent_id, int) and sent_id not in ids:
        ids.append(sent_id)
    await state.update_data(entry_message_ids=ids)


async def _delete_entry_messages(message: Message, ids: list[int]) -> None:
    """Убрать сообщения завершённого диалога, не влияя на сохранённую ставку."""
    bot = getattr(message, "bot", None)
    if bot is None:
        return
    for message_id in dict.fromkeys(ids):
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message_id)
        except TelegramAPIError as exc:
            logger.warning("Не удалось удалить сообщение диалога ставки %s: %s", message_id, exc)


class BetEntryState(StatesGroup):
    """Шаги ввода фактического размещения."""

    waiting_stake = State()
    waiting_odds = State()
    waiting_placed_at = State()


class BetSettlementState(StatesGroup):
    """Шаги ручного расчёта ставки."""

    waiting_payout = State()
    waiting_settled_at = State()


def _private_owner(event: Message | CallbackQuery, cfg: DictConfig) -> int | None:
    """Разрешить денежный журнал только владельцу в личном чате."""
    user = event.from_user
    message = getattr(event, "message", event)
    chat = getattr(message, "chat", None)
    admins = {int(value) for value in (cfg.bot.get("admin_user_ids") or []) if value is not None}
    configured = str(cfg.bot.get("bets_owner_id") or "").strip()
    if (
        user is None
        or not configured.isdigit()
        or int(user.id) != int(configured)
        or int(user.id) not in admins
        or getattr(chat, "type", None) != "private"
    ):
        return None
    return int(user.id)


async def create_card_context(
    cfg: DictConfig, owner_id: int, prediction: dict[str, Any]
) -> dict[str, Any]:
    """Закрепить ровно тот payload, который затем будет показан в карточке."""
    return await _control_request(
        cfg, owner_id, "POST", "bet-contexts", payload={"prediction": prediction}
    )


def card_context_button(context_id: str) -> InlineKeyboardMarkup:
    """Кнопка ручной записи ставки для сохранённого контекста."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Записать ставку", callback_data=f"bet:new:{context_id}")]
        ]
    )


def _outcome_label(outcome: str, market_spec: str) -> str:
    """Показать владельцу исход с учётом правил рынка."""
    labels = {
        "home_win": "Победа хозяев",
        "away_win": "Победа гостей",
        "draw": "Ничья",
    }
    label = labels.get(outcome, outcome.replace("_", " "))
    if market_spec == "winner_withOT" and outcome in {"home_win", "away_win"}:
        return f"{label} с ОТ/буллитами"
    if market_spec == "winner_1x2":
        return f"{label} (основное время)"
    return label


def _market_label(market_spec: str) -> str:
    """Показать период и значимые правила ручного рынка."""
    return {
        "winner_withOT": "Победитель матча с ОТ/буллитами",
        "winner_1x2": "1X2, основное время",
        "winner": "Победитель матча",
    }.get(market_spec, market_spec)


def _correction_outcome_hint(market_spec: str, bet_id: str) -> str:
    """Показать допустимые исходы и копируемый пример для ставки."""
    outcomes = MARKET_OUTCOMES.get(market_spec)
    if not outcomes:
        return ""
    choices = ", ".join(outcomes[:-1]) + f" или {outcomes[-1]}"
    example = "draw" if "draw" in outcomes else outcomes[0]
    return f"Для этой ставки исходы: {choices}. Пример: /bet_correct {bet_id} outcome {example}"


def _uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _rub(value: str, *, positive: bool) -> str | None:
    try:
        amount = Decimal(value.replace(",", ".").strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        return None
    if amount <= 0 if positive else amount < 0:
        return None
    return f"{amount:.2f}"


def _odds(value: str) -> str | None:
    try:
        odds = Decimal(value.replace(",", ".").strip())
    except InvalidOperation:
        return None
    if not odds.is_finite() or odds <= 1 or odds != odds.quantize(Decimal("0.0001")):
        return None
    return str(odds)


def _manual_time(value: str) -> str | None:
    try:
        local = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=_MOSCOW)
    except ValueError:
        return None
    return local.astimezone(UTC).isoformat()


def _time_buttons(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сейчас", callback_data=f"bet:{kind}:now")],
            [InlineKeyboardButton(text="Указать время", callback_data=f"bet:{kind}:manual")],
        ]
    )


async def _show_entry_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    placed_at = datetime.fromisoformat(str(data["placed_at"])).astimezone(_MOSCOW)
    funding = "фрибет" if data["funding"] == "freebet" else "свои деньги"
    await _entry_answer(
        message,
        state,
        "Проверьте ставку перед сохранением:\n"
        f"Турнир: {escape(str(data.get('tournament') or 'не указан'))}\n"
        f"Матч: {escape(str(data['match_label']))}\n"
        f"Рынок: {escape(_market_label(str(data['market_spec'])))}; "
        f"исход: {escape(_outcome_label(str(data['outcome']), str(data['market_spec'])))}\n"
        f"Winline: {escape(str(data['stake']))} ₽ × {escape(str(data['decimal_odds']))}\n"
        f"Средства: {funding}; размещена: {placed_at:%d.%m.%Y %H:%M} МСК\n"
        f"Версия прогноза: {escape(str(data.get('prediction_revision_id') or 'нет подтверждённой'))}; "
        f"ID котировки: {escape(str(data.get('quote_observation_id') or 'нет'))}\n"
        + (
            "Выигрыш фрибета выплачивается без номинала."
            if data["funding"] == "freebet"
            else "При выигрыше выплата включает сумму ставки."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Сохранить", callback_data="bet:confirm")]
            ]
        ),
    )


@router.callback_query(F.data.startswith("bet:new:"))
async def cb_new_bet(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    owner_id = _private_owner(cq, cfg)
    context_id = _uuid((cq.data or "").removeprefix("bet:new:"))
    if owner_id is None or context_id is None or cq.message is None:
        await cq.answer("Запись доступна владельцу в личном чате.", show_alert=True)
        return
    try:
        context = await _control_request(cfg, owner_id, "GET", f"bet-contexts/{context_id}")
    except ControlApiError:
        await cq.answer("Карточка недоступна.", show_alert=True)
        return
    prediction = context.get("prediction") or {}
    outcomes = list(
        prediction.get("available_outcomes") or (prediction.get("predictions") or {}).keys()
    )
    if not outcomes and prediction.get("market_spec") == "winner_withOT":
        outcomes = ["home_win", "away_win"]
    if not outcomes or len(outcomes) > 10:
        await cq.answer("Исходы прогноза недоступны.", show_alert=True)
        return
    await state.clear()
    await state.update_data(
        context_id=context_id,
        outcomes=outcomes,
        tournament=prediction.get("tournament"),
        market_spec=prediction.get("market_spec"),
        match_label=f"{prediction.get('home_player') or 'Home'} — {prediction.get('away_player') or 'Away'}",
        prediction_revision_id=context.get("prediction_revision_id"),
        quote_observation_id=context.get("quote_observation_id"),
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_outcome_label(outcome, str(prediction.get("market_spec") or "")),
                    callback_data=f"bet:outcome:{index}",
                )
            ]
            for index, outcome in enumerate(outcomes)
        ]
    )
    await _entry_answer(
        cast(Message, cq.message),
        state,
        "Выберите фактический исход ставки:",
        remember_incoming=False,
        reply_markup=keyboard,
    )
    await cq.answer()


@router.callback_query(F.data.startswith("bet:outcome:"))
async def cb_bet_outcome(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    raw_index = (cq.data or "").removeprefix("bet:outcome:")
    outcomes = data.get("outcomes") or []
    if not raw_index.isdigit() or int(raw_index) >= len(outcomes):
        await cq.answer("Начните запись с карточки прогноза.", show_alert=True)
        return
    await state.update_data(outcome=outcomes[int(raw_index)])
    await _entry_answer(
        cast(Message, cq.message),
        state,
        "Чем сделали ставку?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Свои деньги", callback_data="bet:funding:cash")],
                [InlineKeyboardButton(text="Фрибет", callback_data="bet:funding:freebet")],
            ]
        ),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("bet:funding:"))
async def cb_bet_funding(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    funding = (cq.data or "").removeprefix("bet:funding:")
    data = await state.get_data()
    if funding not in {"cash", "freebet"} or "outcome" not in data:
        await cq.answer("Начните запись с карточки прогноза.", show_alert=True)
        return
    await state.update_data(funding=funding)
    await state.set_state(BetEntryState.waiting_stake)
    await _entry_answer(
        cast(Message, cq.message), state, "Введите сумму в рублях, например 500 или 500,50:"
    )
    await cq.answer()


@router.message(BetEntryState.waiting_stake, ~F.text.startswith("/"))
async def msg_bet_stake(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(message, cfg) is None:
        return
    stake = _rub(message.text or "", positive=True)
    if stake is None:
        await _entry_answer(
            message, state, "Введите положительную сумму в рублях с точностью до копейки."
        )
        return
    await state.update_data(stake=stake)
    await state.set_state(BetEntryState.waiting_odds)
    await _entry_answer(message, state, "Введите фактический коэффициент Winline, например 2,35:")


@router.message(BetEntryState.waiting_odds, ~F.text.startswith("/"))
async def msg_bet_odds(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(message, cfg) is None:
        return
    odds = _odds(message.text or "")
    if odds is None:
        await _entry_answer(
            message, state, "Введите decimal коэффициент больше 1, максимум 4 знака после запятой."
        )
        return
    await state.update_data(decimal_odds=odds)
    await _entry_answer(
        message, state, "Когда разместили ставку?", reply_markup=_time_buttons("placed")
    )


@router.callback_query(F.data.startswith("bet:placed:"))
async def cb_bet_placed(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    if "decimal_odds" not in data:
        await cq.answer("Начните запись с карточки прогноза.", show_alert=True)
        return
    choice = (cq.data or "").removeprefix("bet:placed:")
    if choice == "now":
        await state.update_data(placed_at=datetime.now(UTC).isoformat(), request_id=str(uuid4()))
        await _show_entry_confirmation(cast(Message, cq.message), state)
    elif choice == "manual":
        await state.set_state(BetEntryState.waiting_placed_at)
        await _entry_answer(
            cast(Message, cq.message), state, "Введите время размещения: ДД.ММ.ГГГГ ЧЧ:ММ МСК"
        )
    else:
        await cq.answer("Неизвестный выбор.", show_alert=True)
        return
    await cq.answer()


@router.message(BetEntryState.waiting_placed_at, ~F.text.startswith("/"))
async def msg_bet_placed(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(message, cfg) is None:
        return
    placed_at = _manual_time(message.text or "")
    if placed_at is None:
        await _entry_answer(message, state, "Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ МСК.")
        return
    await state.update_data(placed_at=placed_at, request_id=str(uuid4()))
    await _show_entry_confirmation(message, state)


@router.callback_query(F.data == "bet:confirm")
async def cb_bet_confirm(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    owner_id = _private_owner(cq, cfg)
    if owner_id is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    fields = (
        "context_id",
        "outcome",
        "funding",
        "stake",
        "decimal_odds",
        "placed_at",
        "request_id",
    )
    if any(field not in data for field in fields):
        await cq.answer("Начните запись с карточки прогноза.", show_alert=True)
        return
    try:
        response = await _control_request(
            cfg,
            owner_id,
            "POST",
            "bets",
            payload={field: data[field] for field in fields if field != "request_id"},
            idempotency_key=str(data["request_id"]),
        )
    except ControlApiError:
        await cq.answer("Не удалось сохранить ставку. Повторите подтверждение.", show_alert=True)
        return
    sent = await cq.message.answer(
        f"Ставка сохранена: <code>{escape(str(response['bet_id']))}</code>. Добор запишите отдельной ставкой."
    )
    ids = list(data.get("entry_message_ids") or [])
    confirmation_id = getattr(cq.message, "message_id", None)
    if isinstance(confirmation_id, int):
        ids.append(confirmation_id)
    sent_id = getattr(sent, "message_id", None)
    if isinstance(sent_id, int):
        ids.append(sent_id)
    await state.clear()
    await _delete_entry_messages(cast(Message, cq.message), ids)
    await cq.answer("Ставка сохранена")


@router.message(Command("bets"))
async def cmd_bets(message: Message, cfg: DictConfig) -> None:
    """Показать открытые ставки с кнопкой ручного расчёта."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    try:
        response = await _control_request(cfg, owner_id, "GET", "bets", params={"status": "open"})
    except ControlApiError:
        await message.answer("Журнал временно недоступен.")
        return
    bets = response.get("bets") or []
    if not bets:
        await message.answer("Открытых ставок нет.")
        return
    for bet in bets[:20]:
        bet_id = str(bet["bet_id"])
        await message.answer(
            f"<code>{escape(bet_id)}</code> · {escape(str(bet['tournament']))} · "
            f"{escape(str(bet['match_id']))}\n"
            f"{escape(str(bet['outcome']))}: {escape(str(bet['stake']))} ₽ × {escape(str(bet['decimal_odds']))}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Рассчитать", callback_data=f"bet:settle:{bet_id}")]
                ]
            ),
        )


@router.message(Command("bet_add"))
async def cmd_bet_add(message: Message, cfg: DictConfig) -> None:
    """Начать запись из календарного матча указанного турнира без прогноза."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    parts = (message.text or "").split()
    if (
        len(parts) != 3
        or not parts[1].replace("_", "").replace("-", "").isalnum()
        or not parts[2].replace("-", "").isalnum()
    ):
        await message.answer(
            "Используйте /bet_add турнир ID_матча, например /bet_add nhl 2026020084."
        )
        return
    try:
        context = await _control_request(
            cfg,
            owner_id,
            "POST",
            "bet-contexts/manual",
            payload={"tournament": parts[1], "match_id": parts[2]},
        )
    except ControlApiError as exc:
        if exc.status_code == 404:
            await message.answer("Матч не найден. Проверьте турнир и ID в календаре.")
        elif exc.status_code == 422:
            await message.answer(
                "Для матча нет однозначного поддерживаемого рынка. Проверьте турнир и ID."
            )
        else:
            await message.answer("Журнал временно недоступен.")
        return
    prediction = context["prediction"]
    await message.answer(
        f"Турнир: {escape(str(prediction.get('tournament') or parts[1]))}\n"
        f"Матч: {escape(str(prediction.get('home_player') or 'Home'))} — "
        f"{escape(str(prediction.get('away_player') or 'Away'))}\n"
        f"Рынок: {escape(_market_label(str(prediction.get('market_spec') or '')))}\n"
        "Прогноза и Pinnacle-котировки нет; ставка будет записана без этих ссылок.",
        reply_markup=card_context_button(str(context["context_id"])),
    )


@router.callback_query(F.data.startswith("bet:settle:"))
async def cb_bet_settle(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    owner_id = _private_owner(cq, cfg)
    bet_id = _uuid((cq.data or "").removeprefix("bet:settle:"))
    if owner_id is None or bet_id is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    try:
        bet = await _control_request(cfg, owner_id, "GET", f"bets/{bet_id}")
    except ControlApiError:
        await cq.answer("Ставка недоступна.", show_alert=True)
        return
    if bet.get("status") != "open":
        await cq.answer("Ставка уже рассчитана.", show_alert=True)
        return
    await state.clear()
    await state.update_data(bet_id=bet_id, expected_revision=bet["revision"], bet=bet)
    await cq.message.answer(
        "Как рассчитана ставка?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Выигрыш", callback_data="bet:result:win")],
                [InlineKeyboardButton(text="Проигрыш", callback_data="bet:result:loss")],
                [InlineKeyboardButton(text="Возврат", callback_data="bet:result:void")],
            ]
        ),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("bet:result:"))
async def cb_bet_result(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    result = (cq.data or "").removeprefix("bet:result:")
    data = await state.get_data()
    if result not in {"win", "loss", "void"} or "bet_id" not in data:
        await cq.answer("Выберите ставку из /bets.", show_alert=True)
        return
    bet = data["bet"]
    nominal = Decimal(str(bet["stake"]))
    odds = Decimal(str(bet["decimal_odds"]))
    funding: Funding = "cash" if bet["funding"] == "cash" else "freebet"
    settlement: Result = "win" if result == "win" else "loss" if result == "loss" else "void"
    expected = expected_payout(nominal, odds, funding, settlement)
    await state.update_data(result=result, expected_payout=f"{expected:.2f}")
    await state.set_state(BetSettlementState.waiting_payout)
    await cq.message.answer(
        f"Введите фактически полученную выплату в рублях. Ожидается {expected:.2f} ₽.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Получено {expected:.2f} ₽", callback_data="bet:payout:expected"
                    )
                ]
            ]
        ),
    )
    await cq.answer()


async def _ask_settlement_time(message: Message, state: FSMContext, payout: str) -> None:
    await state.update_data(payout=payout)
    await message.answer("Когда рассчитана ставка?", reply_markup=_time_buttons("settled"))


@router.callback_query(F.data == "bet:payout:expected")
async def cb_expected_payout(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    if "expected_payout" not in data:
        await cq.answer("Выберите ставку из /bets.", show_alert=True)
        return
    await _ask_settlement_time(cast(Message, cq.message), state, str(data["expected_payout"]))
    await cq.answer()


@router.message(BetSettlementState.waiting_payout, ~F.text.startswith("/"))
async def msg_bet_payout(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(message, cfg) is None:
        return
    payout = _rub(message.text or "", positive=False)
    if payout is None:
        await message.answer("Введите неотрицательную выплату в рублях с точностью до копейки.")
        return
    await _ask_settlement_time(message, state, payout)


async def _show_settlement_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    settled_at = datetime.fromisoformat(str(data["settled_at"])).astimezone(_MOSCOW)
    await message.answer(
        f"Проверьте расчёт <code>{escape(str(data['bet_id']))}</code>:\n"
        f"{escape(str(data['result']))}, выплата {escape(str(data['payout']))} ₽, "
        f"{settled_at:%d.%m.%Y %H:%M} МСК.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Сохранить расчёт", callback_data="bet:settle_confirm"
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("bet:settled:"))
async def cb_bet_settled_time(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(cq, cfg) is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    if "payout" not in data:
        await cq.answer("Выберите ставку из /bets.", show_alert=True)
        return
    choice = (cq.data or "").removeprefix("bet:settled:")
    if choice == "now":
        await state.update_data(settled_at=datetime.now(UTC).isoformat(), request_id=str(uuid4()))
        await _show_settlement_confirmation(cast(Message, cq.message), state)
    elif choice == "manual":
        await state.set_state(BetSettlementState.waiting_settled_at)
        await cq.message.answer("Введите время расчёта: ДД.ММ.ГГГГ ЧЧ:ММ МСК")
    else:
        await cq.answer("Неизвестный выбор.", show_alert=True)
        return
    await cq.answer()


@router.message(BetSettlementState.waiting_settled_at, ~F.text.startswith("/"))
async def msg_bet_settled_time(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    if _private_owner(message, cfg) is None:
        return
    settled_at = _manual_time(message.text or "")
    if settled_at is None:
        await message.answer("Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ МСК.")
        return
    await state.update_data(settled_at=settled_at, request_id=str(uuid4()))
    await _show_settlement_confirmation(message, state)


@router.callback_query(F.data == "bet:settle_confirm")
async def cb_bet_settle_confirm(cq: CallbackQuery, cfg: DictConfig, state: FSMContext) -> None:
    owner_id = _private_owner(cq, cfg)
    if owner_id is None or cq.message is None:
        await cq.answer("Недостаточно прав.", show_alert=True)
        return
    data = await state.get_data()
    fields = ("bet_id", "expected_revision", "result", "payout", "settled_at", "request_id")
    if any(field not in data for field in fields):
        await cq.answer("Выберите ставку из /bets.", show_alert=True)
        return
    try:
        bet = await _control_request(
            cfg,
            owner_id,
            "PATCH",
            f"bets/{data['bet_id']}",
            payload={
                field: data[field] for field in fields if field not in {"bet_id", "request_id"}
            },
            idempotency_key=str(data["request_id"]),
        )
    except ControlApiError:
        await cq.answer("Расчёт не сохранён. Проверьте ставку и повторите.", show_alert=True)
        return
    await state.clear()
    difference = bet.get("payout_difference")
    note = (
        f" Расхождение с формулой: {escape(str(difference))} ₽."
        if difference not in {None, "0.00"}
        else ""
    )
    await cq.message.answer(f"Расчёт сохранён.{note}")
    await cq.answer()


@router.message(Command("bet_report"))
async def cmd_bet_report(message: Message, cfg: DictConfig) -> None:
    """Показать месяц или сезон по фактически рассчитанным ставкам."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    argument = (message.text or "").split(maxsplit=1)
    parts = argument[1].strip().split() if len(argument) == 2 else []
    if parts and parts[0] in {"season", "сезон"}:
        if len(parts) > 2:
            await message.answer("Используйте /bet_report season [турнир]")
            return
        tournament = parts[1] if len(parts) == 2 else "nhl"
        try:
            report = await _control_request(
                cfg, owner_id, "GET", "bets/season-summary", params={"tournament": tournament}
            )
        except ControlApiError:
            await message.answer("Сезонный отчёт недоступен или не настроен для турнира.")
            return
        await message.answer(
            f"Фактические ставки · {escape(str(report['tournament']).upper())} · "
            f"{report['start']}—{report['end']} (МСК)\n"
            f"Рассчитано: {report['settled_count']}; открыто: {report['open_count']}\n"
            f"Свои: оборот {report['cash_turnover']} ₽, PnL {report['cash_pnl']} ₽, "
            f"ROI {report['cash_roi'] or '—'}\n"
            f"Фрибеты: номинал {report['freebet_nominal']} ₽, "
            f"выплата {report['freebet_payout']} ₽\n"
            f"Общий денежный PnL: {report['total_cash_pnl']} ₽; "
            f"hit rate: {report['hit_rate'] or '—'}"
        )
        try:
            chart = render_season_pnl_chart(
                start=report["start"],
                end=report["end"],
                tournament=report["tournament"],
                points=report["daily_pnl"],
            )
            await message.answer_photo(BufferedInputFile(chart, filename="season-pnl.png"))
        except (KeyError, ValueError, TypeError, TelegramAPIError):
            logger.warning("Не удалось показать график сезонного отчёта")
            await message.answer("График временно недоступен.")
        return
    try:
        month = (
            datetime.strptime(argument[1], "%Y-%m") if len(argument) == 2 else datetime.now(_MOSCOW)
        )
    except ValueError:
        await message.answer("Используйте /bet_report ГГГГ-ММ")
        return
    try:
        report = await _control_request(
            cfg, owner_id, "GET", "bets/summary", params={"year": month.year, "month": month.month}
        )
    except ControlApiError:
        await message.answer("Отчёт временно недоступен.")
        return
    breakdown = []
    for title, key in (
        ("Букмекеры", "by_bookmaker"),
        ("Рынки", "by_market"),
        ("Средства", "by_funding"),
        ("Турниры", "by_tournament"),
    ):
        items = report.get(key) or {}
        if items:
            breakdown.append(
                f"{title}: "
                + "; ".join(
                    f"{escape(str(name))} — {escape(str(values['total_cash_pnl']))} ₽"
                    for name, values in items.items()
                )
            )
    await message.answer(
        f"Фактические ставки за {month:%m.%Y} (по расчёту МСК)\n"
        f"Рассчитано: {report['settled_count']}; открыто: {report['open_count']}\n"
        f"Свои: оборот {report['cash_turnover']} ₽, PnL {report['cash_pnl']} ₽, ROI {report['cash_roi'] or '—'}\n"
        f"Фрибеты: номинал {report['freebet_nominal']} ₽, выплата {report['freebet_payout']} ₽\n"
        f"Общий денежный PnL: {report['total_cash_pnl']} ₽; hit rate: {report['hit_rate'] or '—'}"
        + ("\n" + "\n".join(breakdown) if breakdown else "")
    )


@router.message(Command("bet_history"))
async def cmd_bet_history(message: Message, cfg: DictConfig) -> None:
    """Показать последние фактические ставки, включая рассчитанные."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    try:
        response = await _control_request(cfg, owner_id, "GET", "bets")
    except ControlApiError:
        await message.answer("Журнал временно недоступен.")
        return
    bets = response.get("bets") or []
    if not bets:
        await message.answer("Записей пока нет.")
        return
    lines = [
        f"<code>{escape(str(bet['bet_id']))}</code> · {escape(str(bet['tournament']))} · "
        f"{escape(str(bet['match_id']))} · {escape(str(bet['market_spec']))} · "
        f"{escape(str(bet['outcome']))} · {bet['stake']} ₽ × {bet['decimal_odds']} · "
        f"{escape(str(bet['status']))}"
        for bet in bets[:20]
    ]
    await message.answer("Последние ставки:\n" + "\n".join(lines))


@router.message(Command("bet_audit"))
async def cmd_bet_audit(message: Message, cfg: DictConfig) -> None:
    """Показать историю изменений одной записи."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    parts = (message.text or "").split(maxsplit=1)
    bet_id = _uuid(parts[1].strip()) if len(parts) == 2 else None
    if bet_id is None:
        await message.answer("Используйте /bet_audit ID_ставки")
        return
    try:
        response = await _control_request(cfg, owner_id, "GET", f"bets/{bet_id}/audit")
    except ControlApiError:
        await message.answer("История недоступна.")
        return
    lines = [
        f"{escape(str(event['created_at']))} · {escape(str(event['operation']))}: "
        f"{escape(str(event['after'].get('status')))} / {escape(str(event['after'].get('payout') or '—'))} ₽"
        for event in (response.get("events") or [])[-20:]
    ]
    await message.answer("История ставки:\n" + "\n".join(lines))


@router.message(Command("bet_correct"))
async def cmd_bet_correct(message: Message, cfg: DictConfig) -> None:
    """Исправить поле ставки, сохранив прежнее значение в audit."""
    owner_id = _private_owner(message, cfg)
    if owner_id is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    parts = (message.text or "").split(maxsplit=3)
    bet_id = _uuid(parts[1]) if len(parts) >= 2 else None
    if bet_id is None or len(parts) < 3:
        outcome_hint = ""
        if bet_id is not None:
            try:
                bet = await _control_request(cfg, owner_id, "GET", f"bets/{bet_id}")
            except ControlApiError:
                bet = {}
            hint = _correction_outcome_hint(str(bet.get("market_spec") or ""), bet_id)
            if hint:
                outcome_hint = "\n" + hint
        await message.answer(_CORRECTION_HELP + outcome_hint)
        return
    field = parts[2]
    value = parts[3] if len(parts) == 4 else ""
    patch: dict[str, Any]
    if field in {"payout", "stake"}:
        amount = _rub(value, positive=field == "stake")
        if amount is None:
            example = "stake 500,50" if field == "stake" else "payout 1176,18"
            await message.answer(
                f"Введите сумму в рублях до копейки: /bet_correct ID_ставки {example}"
            )
            return
        patch = {field: amount}
    elif field == "odds":
        odds = _odds(value)
        if odds is None:
            await message.answer(
                "Коэффициент больше 1, до 4 знаков: /bet_correct ID_ставки odds 2,35"
            )
            return
        patch = {"decimal_odds": odds}
    elif field in {"placed_at", "settled_at"}:
        timestamp = _manual_time(value)
        if timestamp is None:
            await message.answer(
                f"Время ДД.ММ.ГГГГ ЧЧ:ММ МСК: /bet_correct ID_ставки {field} 11.10.2026 19:30"
            )
            return
        patch = {field: timestamp}
    elif field == "funding" and value in {"cash", "freebet"}:
        patch = {"funding": value}
    elif field == "result" and value in {"win", "loss", "void"}:
        patch = {"result": value}
    elif field == "outcome" and value:
        patch = {"outcome": value}
    elif field == "cancel" and value.strip():
        patch = {"status": "cancelled", "cancel_reason": value.strip()}
    elif field == "reopen" and not value:
        patch = {"status": "open"}
    else:
        await message.answer("Недопустимое поле или значение.\n" + _CORRECTION_HELP)
        return
    try:
        bet = await _control_request(cfg, owner_id, "GET", f"bets/{bet_id}")
        if field == "outcome":
            market_spec = str(bet.get("market_spec") or "")
            allowed_outcomes = MARKET_OUTCOMES.get(market_spec)
            if allowed_outcomes is not None and value not in allowed_outcomes:
                await message.answer(_correction_outcome_hint(market_spec, bet_id))
                return
        updated = await _control_request(
            cfg,
            owner_id,
            "PATCH",
            f"bets/{bet_id}",
            payload={"expected_revision": bet["revision"], **patch},
            idempotency_key=f"telegram:correct:{message.chat.id}:{message.message_id}",
        )
    except ControlApiError:
        await message.answer(
            "Исправление не сохранено. Проверьте состояние ставки через /bet_history."
        )
        return
    await message.answer(
        f"Исправлено: <code>{escape(bet_id)}</code>, версия {updated['revision']}. "
        f"История: /bet_audit {escape(bet_id)}"
    )


@router.message(Command("bet_cancel"))
async def cmd_bet_cancel(message: Message, cfg: DictConfig, state: FSMContext) -> None:
    """Закрыть незавершённый диалог без записи денежной операции."""
    if _private_owner(message, cfg) is None:
        await message.answer("Журнал доступен владельцу в личном чате.")
        return
    await state.clear()
    await message.answer("Ввод ставки отменён.")
