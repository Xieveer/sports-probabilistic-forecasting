"""Изоляция admin-уведомлений при неуспехе heavy path."""

from __future__ import annotations

import pytest

from sports_forecast.orchestration.initial_notification import notify_administrators


@pytest.mark.parametrize("failure_kind", ["refresh_failed", "quality_gate_failed"])
def test_failure_notification_targets_only_admins(monkeypatch, failure_kind: str) -> None:
    """Служебный текст не попадает allowlist-получателям и не раскрывает секреты."""
    import sports_forecast.orchestration.initial_notification as subject

    sent: list[tuple[str, str]] = []

    def send(*, token: str, chat_id: str, text: str) -> dict[str, bool]:
        sent.append((chat_id, text))
        return {"ok": True}

    monkeypatch.setattr(
        subject,
        "telegram_send_message",
        send,
    )

    notify_administrators(
        admin_chat_ids=("901", "902"),
        token="secret-token",
        failure_kind=failure_kind,
    )

    assert [chat_id for chat_id, _ in sent] == ["901", "902"]
    assert all("secret-token" not in text for _, text in sent)
    assert all("101" not in chat_id for chat_id, _ in sent)
