"""Стартовое сообщение о проверенном выпуске на сервере."""

from pathlib import Path

import pytest

from sports_forecast.deploy import release_announcement_cli
from sports_forecast.deploy.release_announcement_cli import format_release_announcement


def test_release_message_contains_version_and_brief_changes() -> None:
    """Владелец видит фактическую версию и краткие изменения."""
    message = format_release_announcement(
        "1.4.0", ["Цикл работает с локальными образами", "Ставки рассчитываются автоматически"]
    )
    assert "1.4.0" in message
    assert "Цикл работает" in message
    assert "Ставки рассчитываются" in message


def test_release_message_rejects_untrusted_version_or_empty_changes() -> None:
    """Неверные release notes не уходят в Telegram."""
    with pytest.raises(ValueError):
        format_release_announcement("<unsafe>", ["Изменение"])
    with pytest.raises(ValueError):
        format_release_announcement("1.4.0", [])


def test_announcement_requires_running_version_to_match_image_notes(
    monkeypatch, tmp_path: Path
) -> None:
    """Нельзя отправить сообщение от имени другой версии образа."""
    notes = tmp_path / "release-notes.yaml"
    notes.write_text('version: "1.4.0"\nchanges:\n  - "Новый отчёт"\n', encoding="utf-8")
    token = tmp_path / "bot-token"
    token.write_text("dummy-token", encoding="utf-8")
    monkeypatch.setattr(release_announcement_cli, "_NOTES_PATH", notes)
    monkeypatch.setenv("SF_APP_VERSION", "1.3.7")
    monkeypatch.setenv("BOT_BETS_OWNER_ID", "101")
    monkeypatch.setenv("BOT_TOKEN_FILE", str(token))
    sent: list[tuple[int, str]] = []

    async def fake_send(_token: str, owner_id: int, message: str) -> None:
        sent.append((owner_id, message))

    monkeypatch.setattr(release_announcement_cli, "_send", fake_send)
    assert release_announcement_cli.main() == 1
    assert sent == []
    monkeypatch.setenv("SF_APP_VERSION", "1.4.0")
    assert release_announcement_cli.main() == 0
    assert sent[0][0] == 101
    assert "1.4.0" in sent[0][1]
