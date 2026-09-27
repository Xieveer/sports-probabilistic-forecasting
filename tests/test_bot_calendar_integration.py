"""Кодовый контракт Telegram-календаря с локальным ASGI API."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from omegaconf import OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.bot.handlers import predict
from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import Base, CalendarCoverage, CanonicalEvent
from sports_forecast.service.routers import calendar as calendar_router


class _ScheduleState:
    def __init__(self, period: str) -> None:
        self.data = {"schedule_tournament": "nhl", "schedule_period": period}
        self.cleared = False

    async def get_data(self) -> dict[str, str]:
        return self.data

    async def clear(self) -> None:
        self.cleared = True


def test_telegram_upcoming_reads_calendar_api_at_0300_moscow(monkeypatch) -> None:
    """03:00 «Сегодня» показывает оставшуюся часть начавшихся 08:00 суток."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 26, 0, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="nhl-100",
                scheduled_at=datetime(2026, 9, 26, 4),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="Boston Bruins",
                away_participant="New York Rangers",
                first_ingested_at=datetime(2026, 9, 25, 12),
                last_ingested_at=datetime(2026, 9, 25, 12),
            )
        )
        session.add(
            CalendarCoverage(
                tournament="nhl",
                source="nhl_web_api",
                covered_from=datetime(2026, 9, 25, 5),
                covered_until=datetime(2026, 10, 25, 5),
                complete=True,
                checked_at=datetime(2026, 9, 25, 12),
                last_successful_at=datetime(2026, 9, 25, 12),
            )
        )
        session.commit()

    @contextmanager
    def test_session():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(calendar_router, "get_session", test_session)
    monkeypatch.setattr(calendar_router, "utc_now", lambda: now)

    asgi_client_type = httpx.AsyncClient

    def asgi_client(*_args, **_kwargs):
        return asgi_client_type(
            transport=httpx.ASGITransport(app=app_module.app), base_url="http://test"
        )

    monkeypatch.setattr(predict.httpx, "AsyncClient", asgi_client)
    message = SimpleNamespace(text="", answer=AsyncMock())
    state = _ScheduleState("today")
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://test"}})

    try:
        asyncio.run(predict._send_schedule(message, state, cfg, "today"))
    finally:
        engine.dispose()

    response = "\n".join(call.args[0] for call in message.answer.await_args_list)
    assert state.cleared is True
    assert "Boston Bruins — New York Rangers" in response
    assert "Календарь: актуален" in response
    assert "Прогноз: недоступно" in response
    assert "Коэффициенты: нет данных" in response
    assert "Готовность: частично готово" in response
    assert "07:00 МСК" in response
    assert "03:00 МСК" not in response
