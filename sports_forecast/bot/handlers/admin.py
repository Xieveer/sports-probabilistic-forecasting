"""Административные команды готовности и управления Data Cycle."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

router = Router(name="admin")
_MOSCOW = ZoneInfo("Europe/Moscow")
# В callback toggle остаётся место для префикса, 32-битной revision и действия.
_PIPELINE_SLUG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,37}\Z")
_RUN_STATUS_LABELS = {
    "waiting": "ожидает",
    "running": "выполняется",
    "success": "успешно",
    "partial_success": "частично успешно",
    "failed": "ошибка",
}


class ControlApiError(RuntimeError):
    """Безопасная ошибка control API без тела ответа или секрета."""

    def __init__(self, status_code: int | None = None) -> None:
        super().__init__("Control API недоступен")
        self.status_code = status_code


def _admin_id(event: Message | CallbackQuery) -> int:
    user = event.from_user
    return int(user.id) if user else 0


async def _require_admin(event: Message | CallbackQuery, cfg: DictConfig) -> int | None:
    user_id = _admin_id(event)
    admins = {int(value) for value in (cfg.bot.get("admin_user_ids") or []) if value is not None}
    if user_id not in admins:
        if isinstance(event, CallbackQuery) or hasattr(event, "data"):
            await event.answer("Команда только для администратора.", show_alert=True)
        else:
            await event.answer("Команда только для администратора.")
        return None
    return user_id


def _control_key_file(cfg: DictConfig) -> Path | None:
    raw_path = str(cfg.bot.get("control_api_key_file") or "").strip()
    return Path(raw_path) if raw_path else None


async def _control_request(
    cfg: DictConfig,
    admin_id: int,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    params: dict[str, int | str] | None = None,
) -> dict[str, Any]:
    """Вызвать закрытый API, не показывая пользователю детали транспорта."""
    key_file = _control_key_file(cfg)
    if key_file is None:
        raise ControlApiError
    try:
        service_key = key_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ControlApiError from exc
    if not service_key:
        raise ControlApiError

    base_url = str(cfg.bot.api_base_url).rstrip("/")
    headers = {
        "X-Control-Service-Key": service_key,
        "X-Telegram-Admin-Id": str(admin_id),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method,
                f"{base_url}/admin/{path.lstrip('/')}",
                headers=headers,
                json=payload,
                params=params,
            )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPStatusError as exc:
        raise ControlApiError(exc.response.status_code) from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telegram control API недоступен")
        raise ControlApiError from exc
    if not isinstance(result, dict):
        raise ControlApiError
    return result


def _control_error_message(error: ControlApiError) -> str:
    if error.status_code == 409:
        return "Расписание изменилось одновременно. Откройте /cycle и повторите действие."
    if error.status_code == 422:
        return "Настройка не принята: проверьте допустимое время или интервал."
    if error.status_code == 403:
        return "Control API отклонил доступ. Проверьте права администратора."
    return "Control API недоступен или не настроен. Публичный календарь продолжает работать."


def _cycle_keyboard(schedule: dict[str, Any]) -> InlineKeyboardMarkup:
    pipeline_id = str(schedule["pipeline_id"])
    enabled = bool(schedule.get("enabled"))
    revision = int(schedule["revision"])
    action = "Выключить автоматический цикл" if enabled else "Включить автоматический цикл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=action,
                    callback_data=f"cycle:toggle:{pipeline_id}:{revision}:{int(not enabled)}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Запустить сейчас", callback_data=f"cycle:run:{pipeline_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="История запусков", callback_data=f"cycle:history:{pipeline_id}"
                )
            ],
        ]
    )


def _valid_pipeline_id(pipeline_id: str) -> bool:
    """Разрешить только безопасный slug как сегмент URL и callback payload."""
    return _PIPELINE_SLUG.fullmatch(pipeline_id) is not None


def _run_line(run: dict[str, Any] | None) -> str:
    if not run:
        return "нет"
    run_id = escape(str(run.get("run_id") or "неизвестен"))
    status_value = str(run.get("status") or "неизвестен")
    status = escape(_RUN_STATUS_LABELS.get(status_value, status_value))
    stage = escape(str(run.get("current_stage") or "—"))
    reason = escape(str(run.get("reason") or "—"))
    requested = _format_timestamp(run.get("requested_at") or run.get("started_at"))
    return (
        f"{status}; run_id <code>{run_id}</code>; причина {reason}; "
        f"этап {stage}; время {requested or '—'}"
    )


def _format_timestamp(value: object) -> str:
    if not isinstance(value, str):
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(_MOSCOW).strftime("%d.%m.%Y %H:%M МСК")
    except ValueError:
        return escape(value)


def _cycle_text(schedule: dict[str, Any]) -> str:
    enabled = bool(schedule.get("enabled"))
    dispatcher = "работает" if schedule.get("dispatcher_healthy") else "нет свежего heartbeat"
    return (
        f"<b>Data Cycle {escape(str(schedule.get('pipeline_id') or '—').upper())}</b>\n"
        f"Автоматический цикл: {'включён' if enabled else 'выключен'}\n"
        f"Расписание: {escape(str(schedule.get('base_time', '—')))} "
        f"{escape(str(schedule.get('timezone', '—')))}, "
        f"каждые {escape(str(schedule.get('interval_hours', '—')))} ч\n"
        f"Последний плановый запуск: {_format_timestamp(schedule.get('last_run_at'))}\n"
        f"Следующий запуск: {_format_timestamp(schedule.get('next_run_at')) if schedule.get('next_run_at') else 'не запланирован'}\n"
        f"Dispatcher: {dispatcher}\n"
        f"Текущий цикл: {_run_line(schedule.get('current_run'))}\n"
        f"Предыдущий цикл: {_run_line(schedule.get('last_run'))}\n\n"
        "Время: /cycle_time [турнир] HH:MM; интервал: /cycle_interval [турнир] N."
    )


async def _list_pipelines(cfg: DictConfig, admin_id: int) -> list[dict[str, Any]]:
    response = await _control_request(cfg, admin_id, "GET", "pipelines")
    pipelines = response.get("pipelines")
    if not isinstance(pipelines, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("pipeline_id"), str)
        and _valid_pipeline_id(item["pipeline_id"])
        for item in pipelines
    ):
        raise ControlApiError
    return pipelines


def _select_pipeline(
    pipelines: list[dict[str, Any]], requested: str | None
) -> dict[str, Any] | None:
    """Найти явно выбранный цикл; при нескольких без выбора вернуть None."""
    if requested is None:
        return pipelines[0] if len(pipelines) == 1 else None
    return next((item for item in pipelines if item["pipeline_id"] == requested), None)


def _pipeline_choices(pipelines: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Показать только реально поддерживаемые control API циклы."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(item["pipeline_id"]).upper(),
                    callback_data=f"cycle:select:{item['pipeline_id']}",
                )
            ]
            for item in pipelines
        ]
    )


async def _read_cycle(
    cfg: DictConfig, admin_id: int, requested: str | None = None
) -> dict[str, Any] | None:
    pipelines = await _list_pipelines(cfg, admin_id)
    return _select_pipeline(pipelines, requested)


async def _update_schedule(
    cfg: DictConfig,
    admin_id: int,
    changes: dict[str, Any],
    *,
    pipeline_id: str,
    current: dict[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    if current is None:
        current = await _control_request(cfg, admin_id, "GET", f"pipelines/{pipeline_id}/schedule")
    payload = {
        "expected_revision": expected_revision
        if expected_revision is not None
        else current.get("revision"),
        "enabled": current.get("enabled"),
        "base_time": current.get("base_time"),
        "timezone": current.get("timezone"),
        "interval_hours": current.get("interval_hours"),
        **changes,
    }
    return await _control_request(
        cfg,
        admin_id,
        "PATCH",
        f"pipelines/{pipeline_id}/schedule",
        payload=payload,
    )


async def _request_manual_cycle(
    cfg: DictConfig, admin_id: int, idempotency_key: str, *, pipeline_id: str
) -> dict[str, Any]:
    return await _control_request(
        cfg,
        admin_id,
        "POST",
        f"pipelines/{pipeline_id}/runs",
        idempotency_key=idempotency_key,
    )


async def _send_callback_message(
    cq: CallbackQuery, text: str, *, reply_markup: Any | None = None
) -> None:
    """Отправить результат callback, включая callback без доступного message."""
    message = cq.message
    answer = getattr(message, "answer", None)
    if callable(answer):
        await answer(text, reply_markup=reply_markup)
        return
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    bot = getattr(cq, "bot", None)
    send_message = getattr(bot, "send_message", None)
    if chat_id is not None and callable(send_message):
        await send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


def _manual_cycle_message(run: dict[str, Any]) -> str:
    run_id = escape(str(run.get("run_id") or "неизвестен"))
    status_value = str(run.get("status") or "неизвестен")
    status = escape(_RUN_STATUS_LABELS.get(status_value, status_value))
    stage = escape(str(run.get("current_stage") or "ожидает запуска"))
    created = run.get("created") is True
    if run.get("active_run"):
        accepted = "Цикл принят" if created else "Цикл уже принят или выполняется"
        return f"{accepted}.\nRun ID: <code>{run_id}</code>\nСтатус: {status}; этап: {stage}."
    return f"Повтор запроса уже завершён.\nRun ID: <code>{run_id}</code>\nИтог: {status}."


def _history_text(response: dict[str, Any], pipeline_id: str | None = None) -> str:
    label = f" {escape(pipeline_id.upper())}" if pipeline_id else ""
    lines = [f"<b>Последние циклы{label}</b>"]
    current = response.get("current")
    if isinstance(current, dict):
        lines.append(f"Текущий: {_run_line(current)}")
    runs = response.get("runs")
    if isinstance(runs, list):
        for item in runs:
            if not isinstance(item, dict):
                continue
            raw_summary = item.get("summary")
            summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
            events = escape(str(summary.get("events_found", "n/a")))
            prediction = summary.get("prediction_coverage", {})
            odds = summary.get("odds_coverage", {})
            prediction_text = _format_coverage(prediction)
            odds_text = _format_coverage(odds)
            duration = summary.get("duration_seconds")
            duration_text = f"{int(duration)} с" if isinstance(duration, (int, float)) else "n/a"
            lines.append(
                f"{_format_timestamp(item.get('requested_at'))} · "
                f"{escape(str(item.get('reason') or '—'))} · "
                f"{escape(_RUN_STATUS_LABELS.get(str(item.get('status')), str(item.get('status') or '—')))} · "
                f"<code>{escape(str(item.get('run_id') or '—'))}</code> · событий {events}; "
                f"прогнозы {prediction_text}; коэффициенты {odds_text}; {duration_text}"
            )
    if len(lines) == 1:
        lines.append("История пока пуста.")
    return "\n".join(lines)


def _format_coverage(value: Any) -> str:
    if not isinstance(value, dict):
        return "n/a"
    numerator, denominator = value.get("numerator"), value.get("denominator")
    if numerator is None or denominator is None:
        return "n/a"
    ratio = value.get("ratio")
    percent = f" ({float(ratio):.0%})" if isinstance(ratio, (int, float)) else ""
    return f"{escape(str(numerator))}/{escape(str(denominator))}{percent}"


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


@router.message(Command("status"))
async def cmd_status(message: Message, cfg: DictConfig) -> None:
    """Проверить dependency-aware readiness FastAPI без вывода деталей ошибки."""
    uid = message.from_user.id if message.from_user else 0
    admins = {int(x) for x in (cfg.bot.get("admin_user_ids") or []) if x is not None}
    if not _is_admin(uid, admins):
        await message.answer("Команда только для администратора.")
        return
    base = str(cfg.bot.api_base_url).rstrip("/")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{base}/ready", timeout=30.0)
            r.raise_for_status()
            r.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("Telegram /status: API readiness недоступен")
            await message.answer("API readiness недоступен.")
            return
    await message.answer("API readiness: готов.")


@router.message(Command("cycle"))
async def cmd_cycle(message: Message, cfg: DictConfig) -> None:
    """Показать поддерживаемые циклы или управление выбранным циклом."""
    admin_id = await _require_admin(message, cfg)
    if admin_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) > 2:
        await message.answer("Формат: /cycle [турнир].")
        return
    try:
        pipelines = await _list_pipelines(cfg, admin_id)
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    schedule = _select_pipeline(pipelines, parts[1] if len(parts) == 2 else None)
    if schedule is None:
        await message.answer("Выберите доступный цикл:", reply_markup=_pipeline_choices(pipelines))
        return
    await message.answer(
        _cycle_text(schedule),
        reply_markup=_cycle_keyboard(schedule),
    )


@router.callback_query(F.data.startswith("cycle:select:"))
async def cb_cycle_select(cq: CallbackQuery, cfg: DictConfig) -> None:
    """Открыть выбранный поддерживаемый цикл."""
    admin_id = await _require_admin(cq, cfg)
    if admin_id is None:
        return
    pipeline_id = (cq.data or "").removeprefix("cycle:select:")
    if not _valid_pipeline_id(pipeline_id):
        await cq.answer("Кнопка устарела. Откройте /cycle заново.", show_alert=True)
        return
    await cq.answer()
    try:
        schedule = await _read_cycle(cfg, admin_id, pipeline_id)
    except ControlApiError as exc:
        await _send_callback_message(cq, _control_error_message(exc))
        return
    if schedule is None:
        await _send_callback_message(cq, "Цикл недоступен. Откройте /cycle заново.")
        return
    await _send_callback_message(cq, _cycle_text(schedule), reply_markup=_cycle_keyboard(schedule))


@router.message(Command("cycle_time"))
async def cmd_cycle_time(message: Message, cfg: DictConfig) -> None:
    """Изменить основное время расписания, сохранив остальные параметры."""
    admin_id = await _require_admin(message, cfg)
    if admin_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) not in (2, 3) or len(parts[-1]) != 5 or parts[-1][2] != ":":
        await message.answer("Формат: /cycle_time [турнир] HH:MM (время Europe/Moscow).")
        return
    try:
        hour, minute = (int(value) for value in parts[-1].split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await message.answer("Формат: /cycle_time [турнир] HH:MM (время Europe/Moscow).")
        return
    try:
        selected = await _read_cycle(cfg, admin_id, parts[1] if len(parts) == 3 else None)
        if selected is None:
            await message.answer("Укажите доступный турнир: /cycle_time <турнир> HH:MM.")
            return
        schedule = await _update_schedule(
            cfg, admin_id, {"base_time": parts[-1]}, pipeline_id=str(selected["pipeline_id"])
        )
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    await message.answer(
        f"Основное время: {schedule.get('base_time')} {schedule.get('timezone')}.",
    )


@router.message(Command("cycle_interval"))
async def cmd_cycle_interval(message: Message, cfg: DictConfig) -> None:
    """Изменить интервал повторения цикла в часах."""
    admin_id = await _require_admin(message, cfg)
    if admin_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) not in (2, 3) or not parts[-1].isdigit():
        await message.answer("Формат: /cycle_interval [турнир] N (интервал в часах).")
        return
    try:
        selected = await _read_cycle(cfg, admin_id, parts[1] if len(parts) == 3 else None)
        if selected is None:
            await message.answer("Укажите доступный турнир: /cycle_interval <турнир> N.")
            return
        schedule = await _update_schedule(
            cfg,
            admin_id,
            {"interval_hours": int(parts[-1])},
            pipeline_id=str(selected["pipeline_id"]),
        )
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    await message.answer(f"Интервал: каждые {schedule.get('interval_hours')} ч.")


@router.message(Command("cycle_history"))
async def cmd_cycle_history(message: Message, cfg: DictConfig) -> None:
    """Показать активный и последние завершённые циклы."""
    admin_id = await _require_admin(message, cfg)
    if admin_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) > 2:
        await message.answer("Формат: /cycle_history [турнир].")
        return
    try:
        selected = await _read_cycle(cfg, admin_id, parts[1] if len(parts) == 2 else None)
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    if selected is None:
        await message.answer("Укажите доступный турнир: /cycle_history <турнир>.")
        return
    await _send_cycle_history(message, cfg, admin_id, str(selected["pipeline_id"]))


async def _send_cycle_history(
    message: Message, cfg: DictConfig, admin_id: int, pipeline_id: str
) -> None:
    try:
        response = await _control_request(
            cfg,
            admin_id,
            "GET",
            f"pipelines/{pipeline_id}/runs",
            params={"limit": 10},
        )
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    await message.answer(_history_text(response, pipeline_id))


@router.callback_query(F.data.startswith("cycle:toggle:"))
async def cb_cycle_toggle(cq: CallbackQuery, cfg: DictConfig) -> None:
    """Переключить enabled с актуальной revision расписания."""
    admin_id = await _require_admin(cq, cfg)
    if admin_id is None:
        return
    parts = (cq.data or "").split(":")
    if (
        len(parts) != 5
        or not _valid_pipeline_id(parts[2])
        or not parts[3].isdigit()
        or parts[4] not in {"0", "1"}
    ):
        await cq.answer("Кнопка устарела. Откройте /cycle заново.", show_alert=True)
        return
    await cq.answer()
    expected_revision = int(parts[3])
    pipeline_id = parts[2]
    target_enabled = parts[4] == "1"
    current: dict[str, Any] = {}
    try:
        current = await _control_request(cfg, admin_id, "GET", f"pipelines/{pipeline_id}/schedule")
        schedule = await _update_schedule(
            cfg,
            admin_id,
            {"enabled": target_enabled},
            pipeline_id=pipeline_id,
            current=current,
            expected_revision=expected_revision,
        )
    except ControlApiError as exc:
        if exc.status_code == 409 and bool(current.get("enabled")) == target_enabled:
            await _send_callback_message(cq, "Это действие уже выполнено.")
            return
        await _send_callback_message(cq, _control_error_message(exc))
        return
    await _send_callback_message(
        cq,
        _cycle_text(schedule),
        reply_markup=_cycle_keyboard(schedule),
    )


@router.callback_query(F.data.startswith("cycle:run:"))
async def cb_cycle_run(cq: CallbackQuery, cfg: DictConfig) -> None:
    """Запросить один ручной цикл с Telegram callback idempotency key."""
    admin_id = await _require_admin(cq, cfg)
    if admin_id is None:
        return
    pipeline_id = (cq.data or "").removeprefix("cycle:run:")
    if not _valid_pipeline_id(pipeline_id):
        await cq.answer("Кнопка устарела. Откройте /cycle заново.", show_alert=True)
        return
    await cq.answer()
    try:
        run = await _request_manual_cycle(
            cfg, admin_id, f"bot-callback-{cq.id}", pipeline_id=pipeline_id
        )
    except ControlApiError as exc:
        await _send_callback_message(cq, _control_error_message(exc))
        return
    if run.get("duplicate_request") is True:
        return
    await _send_callback_message(cq, _manual_cycle_message(run))


@router.callback_query(F.data.startswith("cycle:history:"))
async def cb_cycle_history(cq: CallbackQuery, cfg: DictConfig) -> None:
    """Открыть историю циклов из Telegram keyboard."""
    admin_id = await _require_admin(cq, cfg)
    if admin_id is None:
        return
    pipeline_id = (cq.data or "").removeprefix("cycle:history:")
    if not _valid_pipeline_id(pipeline_id):
        await cq.answer("Кнопка устарела. Откройте /cycle заново.", show_alert=True)
        return
    await cq.answer()
    if isinstance(cq.message, Message):
        await _send_cycle_history(cq.message, cfg, admin_id, pipeline_id)


@router.message(Command("refresh"))
async def cmd_refresh(message: Message, cfg: DictConfig) -> None:
    """Legacy alias ручного Data Cycle с дедупликацией по Telegram message ID."""
    admin_id = await _require_admin(message, cfg)
    if admin_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) > 2:
        await message.answer("Формат: /refresh [турнир]. Настройки: /cycle.")
        return
    try:
        selected = await _read_cycle(cfg, admin_id, parts[1] if len(parts) == 2 else None)
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    if selected is None:
        await message.answer("Укажите доступный турнир: /refresh <турнир>.")
        return
    chat_id = message.chat.id if message.chat else admin_id
    message_id = message.message_id
    try:
        run = await _request_manual_cycle(
            cfg,
            admin_id,
            f"bot-message-{chat_id}-{message_id}",
            pipeline_id=str(selected["pipeline_id"]),
        )
    except ControlApiError as exc:
        await message.answer(_control_error_message(exc))
        return
    if run.get("duplicate_request") is True:
        return
    await message.answer(_manual_cycle_message(run))
