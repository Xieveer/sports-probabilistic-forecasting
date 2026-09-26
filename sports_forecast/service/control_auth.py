"""Закрытая авторизация внутренних control API."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Header, HTTPException


def _read_control_key() -> str | None:
    """Прочитать отдельный control credential только из заданного secret file."""
    path = os.environ.get("SF_CONTROL_API_KEY_FILE", "").strip()
    if not path:
        return None
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def configured_admin_ids() -> frozenset[str]:
    """Вернуть настроенные Telegram admin IDs; пустая конфигурация означает deny."""
    raw = os.environ.get("SF_CONTROL_ADMIN_IDS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip().isdigit())


def require_control_admin(
    service_key: str | None = Header(default=None, alias="X-Control-Service-Key"),
    admin_id: str | None = Header(default=None, alias="X-Telegram-Admin-Id"),
) -> str:
    """Проверить service credential и допустимого Telegram admin principal."""
    expected = _read_control_key()
    admins = configured_admin_ids()
    if (
        expected is None
        or not admins
        or service_key is None
        or admin_id is None
        or not hmac.compare_digest(service_key, expected)
        or admin_id not in admins
    ):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return admin_id
