"""Контракт Telegram `/status` с dependency-aware readiness API."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from omegaconf import OmegaConf

from sports_forecast.bot.handlers import admin


def _message() -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )


def test_status_reads_dependency_aware_ready_endpoint(monkeypatch) -> None:
    """Администратор получает readiness, а не liveness payload."""

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, bool]:
            return {"ready": True}

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, *, timeout: float) -> Response:
            assert url == "http://api:8000/ready"
            assert timeout == 30.0
            return Response()

    monkeypatch.setattr(admin.httpx, "AsyncClient", Client)
    message = _message()
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api:8000", "admin_user_ids": [1]}})

    asyncio.run(admin.cmd_status(message, cfg))

    message.answer.assert_awaited_once_with("API readiness: готов.")


def test_status_hides_transport_error_details(monkeypatch) -> None:
    """Сбой readiness не раскрывает URL, exception или response body."""

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, *, timeout: float) -> None:
            raise httpx.ConnectError(
                "postgresql://user:secret@db", request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(admin.httpx, "AsyncClient", Client)
    message = _message()
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api:8000", "admin_user_ids": [1]}})

    asyncio.run(admin.cmd_status(message, cfg))

    message.answer.assert_awaited_once_with("API readiness недоступен.")


def test_status_hides_non_success_response_details(monkeypatch) -> None:
    """Non-2xx readiness не передаёт оператору body ответа."""

    class Response:
        def raise_for_status(self) -> None:
            request = httpx.Request("GET", "http://api:8000/ready")
            response = httpx.Response(503, request=request, text="postgresql://user:secret@db")
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, *, timeout: float) -> Response:
            return Response()

    monkeypatch.setattr(admin.httpx, "AsyncClient", Client)
    message = _message()
    cfg = OmegaConf.create({"bot": {"api_base_url": "http://api:8000", "admin_user_ids": [1]}})

    asyncio.run(admin.cmd_status(message, cfg))

    message.answer.assert_awaited_once_with("API readiness недоступен.")
