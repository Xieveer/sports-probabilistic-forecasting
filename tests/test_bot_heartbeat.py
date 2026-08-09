"""Контракты безопасного heartbeat Telegram bot."""

from __future__ import annotations

import json
from pathlib import Path

from sports_forecast.bot.heartbeat import is_healthy, write_heartbeat


def test_heartbeat_is_fresh_only_when_both_dependencies_are_available(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    write_heartbeat(path, telegram_ok=True, internal_api_ok=True)

    assert is_healthy(path, max_age_seconds=120) is True

    write_heartbeat(path, telegram_ok=True, internal_api_ok=False)
    assert is_healthy(path, max_age_seconds=120) is False


def test_heartbeat_contains_no_tokens_or_user_payload(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    write_heartbeat(path, telegram_ok=True, internal_api_ok=True)

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"updated_at", "telegram_ok", "internal_api_ok"}
    serialized = json.dumps(payload)
    for forbidden in ("token", "chat", "user", "username", "message", "response"):
        assert forbidden not in serialized.lower()
