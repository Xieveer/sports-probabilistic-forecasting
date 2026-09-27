"""Кодовый сценарий Telegram admin → authenticated API → PostgreSQL-like DB."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from omegaconf import OmegaConf
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.bot.handlers import admin, start
from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import Base, DataCycleControlRequest, DataCycleRun
from sports_forecast.service.routers import admin_control


def _message(text: str, user_id: int = 101) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        message_id=42,
        chat=SimpleNamespace(id=101),
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _callback(data: str, callback_id: str, user_id: int = 101) -> SimpleNamespace:
    return SimpleNamespace(
        id=callback_id,
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=_message(""),
        answer=AsyncMock(),
    )


def test_admin_cycle_controls_use_authenticated_api_and_persist_state(
    monkeypatch, tmp_path: Path
) -> None:
    """Админ из Telegram управляет расписанием и запускает идемпотентный цикл через API."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    secret_file = tmp_path / "control_api_key"
    secret_file.write_text("test-control-secret", encoding="utf-8")
    monkeypatch.setenv("SF_CONTROL_API_KEY_FILE", str(secret_file))
    monkeypatch.setenv("SF_CONTROL_ADMIN_IDS", "101")

    @contextmanager
    def control_session():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(admin_control, "get_control_session", control_session)
    original_client = httpx.AsyncClient

    def asgi_client(*_args, **_kwargs):
        return original_client(
            transport=httpx.ASGITransport(app=app_module.app), base_url="http://test"
        )

    monkeypatch.setattr(admin.httpx, "AsyncClient", asgi_client)
    cfg = OmegaConf.create(
        {
            "bot": {
                "api_base_url": "http://test",
                "admin_user_ids": [101],
                "control_api_key_file": str(secret_file),
            }
        }
    )

    try:
        admin_help = _message("/help")
        asyncio.run(start.cmd_help(admin_help, cfg))
        assert "/cycle" in admin_help.answer.await_args.args[0]

        dashboard = _message("/cycle")
        asyncio.run(admin.cmd_cycle(dashboard, cfg))
        assert "Автоматический цикл: включён" in dashboard.answer.await_args.args[0]
        keyboard = dashboard.answer.await_args.kwargs["reply_markup"]
        callback_data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        assert "cycle:toggle:nhl:1:0" in callback_data
        assert "cycle:run:nhl" in callback_data

        time_update = _message("/cycle_time 12:30")
        asyncio.run(admin.cmd_cycle_time(time_update, cfg))
        assert "12:30" in time_update.answer.await_args.args[0]

        interval_update = _message("/cycle_interval 6")
        asyncio.run(admin.cmd_cycle_interval(interval_update, cfg))
        assert "6 ч" in interval_update.answer.await_args.args[0]

        updated_dashboard = _message("/cycle")
        asyncio.run(admin.cmd_cycle(updated_dashboard, cfg))
        updated_keyboard = updated_dashboard.answer.await_args.kwargs["reply_markup"]
        toggle_data = updated_keyboard.inline_keyboard[0][0].callback_data
        toggle = _callback(toggle_data, "toggle-1")
        asyncio.run(admin.cb_cycle_toggle(toggle, cfg))
        assert "выключен" in toggle.message.answer.await_args.args[0]
        replay = _callback(toggle_data, "toggle-1")
        asyncio.run(admin.cb_cycle_toggle(replay, cfg))

        run = _callback("cycle:run:nhl", "run-42")
        asyncio.run(admin.cb_cycle_run(run, cfg))
        first_text = run.message.answer.await_args.args[0]
        assert "Run ID" in first_text
        assert "Цикл принят" in first_text
        run.answer.assert_awaited_once()

        duplicate = _callback("cycle:run:nhl", "run-42")
        asyncio.run(admin.cb_cycle_run(duplicate, cfg))
        duplicate.message.answer.assert_not_called()
        duplicate.answer.assert_awaited_once()
        duplicate_text = first_text

        history = _message("/cycle_history")
        asyncio.run(admin.cmd_cycle_history(history, cfg))
        assert "manual" in history.answer.await_args.args[0]
        assert "ожидает" in history.answer.await_args.args[0]

        refresh_message = _message("/refresh")
        asyncio.run(admin.cmd_refresh(refresh_message, cfg))
        refresh_retry = _message("/refresh")
        asyncio.run(admin.cmd_refresh(refresh_retry, cfg))
        assert "Run ID" in refresh_message.answer.await_args.args[0]
        refresh_retry.answer.assert_not_awaited()

        with Session(engine) as session:
            from sports_forecast.service.db.models import PipelineSchedule

            schedule = session.scalar(select(PipelineSchedule))
            assert schedule is not None
            assert schedule.enabled is False
            assert schedule.base_time == "12:30"
            assert schedule.interval_hours == 6
            stored = session.scalar(select(DataCycleRun))
            requests = list(session.scalars(select(DataCycleControlRequest)))
            assert stored is not None
            assert stored.run_id in duplicate_text
            assert len(requests) == 2
    finally:
        engine.dispose()


def test_non_admin_callback_cannot_change_schedule_or_call_control_api(monkeypatch) -> None:
    """Проверка Telegram ID выполняется и в callback handler."""
    async_client = AsyncMock()
    monkeypatch.setattr(admin.httpx, "AsyncClient", async_client)
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101]}})
    callback = _callback("cycle:toggle:nhl", "toggle-forbidden", user_id=202)

    asyncio.run(admin.cb_cycle_toggle(callback, cfg))

    callback.answer.assert_awaited_once_with("Команда только для администратора.", show_alert=True)
    async_client.assert_not_called()


def test_manual_callback_is_acknowledged_before_api_request(monkeypatch) -> None:
    """Telegram получает callback ack до ожидания сетевого control API."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_request(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return {
            "run_id": "run-id",
            "status": "waiting",
            "current_stage": "waiting",
            "created": True,
            "active_run": True,
            "duplicate_request": False,
        }

    monkeypatch.setattr(admin, "_request_manual_cycle", delayed_request)
    callback = _callback("cycle:run:nhl", "slow-run")
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101]}})

    async def scenario() -> None:
        task = asyncio.create_task(admin.cb_cycle_run(callback, cfg))
        await entered.wait()
        callback.answer.assert_awaited_once_with()
        release.set()
        await task

    asyncio.run(scenario())


def test_manual_callback_sends_result_when_message_is_inaccessible(monkeypatch) -> None:
    """InaccessibleMessage получает результат через bot.send_message."""
    send_message = AsyncMock()
    callback = _callback("cycle:run:nhl", "inaccessible-run")
    callback.message = SimpleNamespace(chat=SimpleNamespace(id=101))
    callback.bot = SimpleNamespace(send_message=send_message)

    async def request(*_args, **_kwargs):
        return {
            "run_id": "run-id",
            "status": "waiting",
            "current_stage": "waiting",
            "created": True,
            "active_run": True,
            "duplicate_request": False,
        }

    monkeypatch.setattr(admin, "_request_manual_cycle", request)
    cfg = OmegaConf.create({"bot": {"admin_user_ids": [101]}})

    asyncio.run(admin.cb_cycle_run(callback, cfg))

    send_message.assert_awaited_once()
    assert "run-id" in send_message.await_args.kwargs["text"]


def test_admin_run_fields_are_html_escaped() -> None:
    """Старый run ID и неожиданный API текст не разрывают Telegram HTML."""
    run = {
        "run_id": "old<&>id",
        "status": "<bad>",
        "current_stage": "<stage>",
        "reason": "<reason>",
        "requested_at": "<invalid-time>",
    }

    line = admin._run_line(run)
    history = admin._history_text({"runs": [run]})

    assert "old&lt;&amp;&gt;id" in line
    assert "&lt;stage&gt;" in line
    assert "&lt;reason&gt;" in line
    assert "&lt;invalid-time&gt;" in line
    assert "<bad>" not in line
    assert "old&lt;&amp;&gt;id" in history
    assert "<reason>" not in history
