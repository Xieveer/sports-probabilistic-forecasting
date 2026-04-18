"""Middleware: whitelist по Telegram ``user_id``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class InjectConfigMiddleware(BaseMiddleware):
    """Кладёт Hydra-конфиг в ``data['cfg']`` для хендлеров."""

    def __init__(self, cfg: object) -> None:
        self._cfg = cfg

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["cfg"] = cast(Any, self._cfg)
        return await handler(event, data)


class AllowedUsersMiddleware(BaseMiddleware):
    """Пропускает только пользователей из ``allowed_user_ids``."""

    def __init__(self, allowed_user_ids: set[int]) -> None:
        self._allowed = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        uid: int | None = None
        if isinstance(event, (Message, CallbackQuery)):
            uid = event.from_user.id if event.from_user else None
        if uid is None:
            return await handler(event, data)
        if uid not in self._allowed:
            logger.warning("bot: отклонён user_id=%s (не в whitelist)", uid)
            return None
        return await handler(event, data)
