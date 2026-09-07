"""Контракт controlled Telegram endpoint для first-rollout gate."""

from __future__ import annotations

from omegaconf import OmegaConf

from sports_forecast.bot.dispatcher import build_dispatcher


def test_bot_uses_opt_in_controlled_telegram_endpoint(monkeypatch) -> None:
    """Test Bot API endpoint не меняет production default и не требует token логирования."""
    monkeypatch.setenv("BOT_TELEGRAM_API_BASE_URL", "http://telegram-test:8081")
    cfg = OmegaConf.create({"bot": {"allowed_user_ids": [1], "admin_user_ids": [1]}})

    bot, _ = build_dispatcher(cfg, "123456:fixture-token")
    try:
        assert bot.session.api.base == "http://telegram-test:8081/bot{token}/{method}"
    finally:
        import asyncio

        asyncio.run(bot.session.close())
