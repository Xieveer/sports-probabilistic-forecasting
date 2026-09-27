"""Фальшивая Telegram-доставка terminal Data Cycle outbox."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from omegaconf import OmegaConf
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.bot import __main__ as bot_main
from sports_forecast.bot.handlers.admin import ControlApiError
from sports_forecast.bot.notifications import (
    NotificationConfigurationError,
    poll_notifications_once,
)
from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import Base, DataCycleNotificationOutbox
from sports_forecast.service.db.repository import DataCycleRunRepository
from sports_forecast.service.routers import admin_control


def _cfg(destinations: dict[str, list[int]] | None = None):
    return OmegaConf.create(
        {
            "bot": {
                "admin_user_ids": [101],
                "notification_destinations": (
                    {"nhl_admins": -100123} if destinations is None else destinations
                ),
            }
        }
    )


def _notification(**overrides):
    return {
        "notification_id": 1,
        "lease_token": "lease-token",
        "destination_alias": "nhl_admins",
        "run_id": "run-1",
        "pipeline_id": "nhl",
        "reason": "scheduled",
        "status": "partial_success",
        "failure_code": None,
        "summary": {
            "events_found": 8,
            "prediction_coverage": {"numerator": 6, "denominator": 8, "ratio": 0.75},
            "odds_coverage": {"numerator": 4, "denominator": 8, "ratio": 0.5},
            "duration_seconds": 91,
        },
        **overrides,
    }


def test_poll_sends_compact_terminal_summary_then_acks(monkeypatch) -> None:
    """Уведомление маршрутизируется по alias, отправляется до durable ack."""
    events: list[tuple[str, Any]] = []
    notification = _notification()

    async def fake_request(_cfg, _admin_id, method, path, **kwargs):
        events.append((method, path))
        if path == "notifications/claim":
            assert method == "POST"
            assert kwargs["payload"] == {"limit": 20}
            return {"notifications": [notification]}
        assert path == "notifications/1/ack"
        assert method == "POST"
        assert kwargs["payload"] == {"lease_token": "lease-token"}
        return {"acknowledged": True}

    monkeypatch.setattr("sports_forecast.bot.notifications._control_request", fake_request)

    async def fake_send_message(**kwargs: Any) -> None:
        events.append(("SEND", kwargs))

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=fake_send_message))

    delivered = asyncio.run(poll_notifications_once(_cfg(), bot))

    assert delivered == 1
    assert [event[0] for event in events] == ["POST", "SEND", "POST"]
    send = events[1][1]
    assert send["chat_id"] == -100123
    assert "частично" in send["text"].lower()
    assert "run-1" in send["text"]
    assert "8" in send["text"] and "6/8" in send["text"] and "4/8" in send["text"]
    assert "91" in send["text"]


def test_unknown_destination_alias_is_neither_sent_nor_acked(monkeypatch) -> None:
    """Misconfigured alias остаётся в lease до expiry и не теряется ack-ом."""
    calls: list[str] = []

    async def fake_request(_cfg, _admin_id, _method, path, **_kwargs):
        calls.append(path)
        if path == "notifications/claim":
            return {"notifications": [_notification(destination_alias="unconfigured")]}
        raise AssertionError("Unknown alias must not be acknowledged or retried")

    monkeypatch.setattr("sports_forecast.bot.notifications._control_request", fake_request)
    bot = SimpleNamespace(send_message=AsyncMock())

    delivered = asyncio.run(poll_notifications_once(_cfg(), bot))

    assert delivered == 0
    assert calls == ["notifications/claim"]
    bot.send_message.assert_not_awaited()


def test_send_failure_requests_safe_retry_without_ack(monkeypatch) -> None:
    """Неуспешная Telegram-доставка назначает backoff и не подтверждает outbox."""
    paths: list[str] = []

    async def fake_request(_cfg, _admin_id, method, path, **kwargs):
        paths.append(path)
        if path == "notifications/claim":
            return {"notifications": [_notification()]}
        assert method == "POST"
        assert path == "notifications/1/retry"
        assert kwargs["payload"] == {
            "lease_token": "lease-token",
            "error_code": "telegram_send_failed",
        }
        return {"retry_scheduled": True}

    monkeypatch.setattr("sports_forecast.bot.notifications._control_request", fake_request)
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("transport detail")))

    delivered = asyncio.run(poll_notifications_once(_cfg(), bot))

    assert delivered == 0
    assert paths == ["notifications/claim", "notifications/1/retry"]


def test_terminal_summary_escapes_run_fields() -> None:
    """Идентификаторы и значения DTO не могут вставить Telegram HTML."""
    from sports_forecast.bot.notifications import format_terminal_notification

    text = format_terminal_notification(
        _notification(run_id="<run&1>", status="failed", failure_code="<unsafe>")
    )

    assert "&lt;run&amp;1&gt;" in text
    assert "&lt;unsafe&gt;" in text
    assert "<unsafe>" not in text


def test_empty_destination_map_is_configuration_error() -> None:
    """Outbox poller явно отклоняет пустую маршрутизацию вместо quiet success."""
    with pytest.raises(NotificationConfigurationError, match="destinations"):
        asyncio.run(poll_notifications_once(_cfg({}), SimpleNamespace(send_message=AsyncMock())))


def test_destination_alias_rejects_multiple_chat_ids() -> None:
    """Один outbox ack соответствует одному Telegram chat destination."""
    with pytest.raises(NotificationConfigurationError, match="один Telegram destination"):
        asyncio.run(
            poll_notifications_once(
                _cfg({"nhl_admins": [-100123, -100456]}),
                SimpleNamespace(send_message=AsyncMock()),
            )
        )


def test_ack_failure_leaves_notification_for_lease_expiry_retry(monkeypatch) -> None:
    """После успешной отправки и неуспешного ack poller не ложно подтверждает row."""
    paths: list[str] = []

    async def fake_request(_cfg, _admin_id, _method, path, **_kwargs):
        paths.append(path)
        if path == "notifications/claim":
            return {"notifications": [_notification()]}
        raise ControlApiError

    monkeypatch.setattr("sports_forecast.bot.notifications._control_request", fake_request)
    bot = SimpleNamespace(send_message=AsyncMock())

    delivered = asyncio.run(poll_notifications_once(_cfg(), bot))

    assert delivered == 0
    assert paths == ["notifications/claim", "notifications/1/ack"]
    bot.send_message.assert_awaited_once()


def test_post_send_crash_window_retries_with_same_run_id(monkeypatch) -> None:
    """At-least-once повтор после send-before-ack узнаётся по постоянному run ID."""
    send_count = 0

    async def fake_request(_cfg, _admin_id, _method, path, **_kwargs):
        nonlocal send_count
        if path == "notifications/claim":
            return {"notifications": [_notification()]}
        if path == "notifications/1/ack":
            send_count += 1
            if send_count == 1:
                raise ControlApiError
            return {"acknowledged": True}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("sports_forecast.bot.notifications._control_request", fake_request)
    bot = SimpleNamespace(send_message=AsyncMock())

    first = asyncio.run(poll_notifications_once(_cfg(), bot))
    second = asyncio.run(poll_notifications_once(_cfg(), bot))

    assert first == 0 and second == 1
    assert bot.send_message.await_count == 2
    assert (
        bot.send_message.await_args_list[0].kwargs["text"]
        == (bot.send_message.await_args_list[1].kwargs["text"])
    )
    assert "run-1" in bot.send_message.await_args_list[0].kwargs["text"]


def test_destination_map_loads_from_runtime_file(tmp_path) -> None:
    """Runtime secret file populates only bot-side alias routing configuration."""
    path = tmp_path / "destinations.json"
    path.write_text(json.dumps({"nhl_admins": -100123}), encoding="utf-8")
    cfg = OmegaConf.create(
        {"bot": {"notification_destinations_file": str(path), "notification_destinations": {}}}
    )

    bot_main._load_notification_destinations(cfg)

    assert cfg.bot.notification_destinations.nhl_admins == -100123


def test_asgi_outbox_response_reaches_fake_telegram_and_acknowledges_db(
    monkeypatch, tmp_path: Path
) -> None:
    """Реальный integer notification DTO проходит poller → fake Telegram → DB ack."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    secret_file = tmp_path / "control_api_key"
    secret_file.write_text("test-control-secret", encoding="utf-8")
    monkeypatch.setenv("SF_CONTROL_API_KEY_FILE", str(secret_file))
    monkeypatch.setenv("SF_CONTROL_ADMIN_IDS", "101")
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl_admins")

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

    monkeypatch.setattr("sports_forecast.bot.handlers.admin.httpx.AsyncClient", asgi_client)
    with Session(engine) as session:
        repository = DataCycleRunRepository(session)
        repository.create(run_id="run-asgi-notification", tournament="nhl", reason="manual")
        repository.start_stage("run-asgi-notification", "calendar")
        repository.fail_run("run-asgi-notification", failure_code="source_fetch_failed")
        session.commit()
    cfg = _cfg()
    cfg.bot.api_base_url = "http://test"
    cfg.bot.control_api_key_file = str(secret_file)
    bot = SimpleNamespace(send_message=AsyncMock())

    delivered = asyncio.run(poll_notifications_once(cfg, bot))

    assert delivered == 1
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == -100123
    assert "run-asgi-notification" in bot.send_message.await_args.kwargs["text"]
    with Session(engine) as session:
        row = session.scalar(select(DataCycleNotificationOutbox))
        assert row is not None and row.status == "delivered"
    engine.dispose()
