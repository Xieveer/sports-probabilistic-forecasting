"""Минимальная отправка сообщений Telegram Bot API (``sendMessage``) без aiogram."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, cast


def telegram_send_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Отправить одно текстовое сообщение в чат через ``sendMessage``.

    Args:
        token: Токен бота.
        chat_id: Идентификатор чата (первый из ``BOT_ALLOWED_USER_IDS`` в типичном сценарии).
        text: Текст (обрезается до ~лимита Telegram).
        timeout_s: Таймаут HTTP в секундах.

    Returns:
        Тело ответа API как dict (поле ``ok`` — успех).

    Raises:
        urllib.error.HTTPError: При не-2xx ответе API.
        urllib.error.URLError: При сетевых сбоях.
        json.JSONDecodeError: Если тело ответа не JSON.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4090]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


__all__ = ["telegram_send_message"]
