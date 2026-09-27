"""Точка входа: ``python -m sports_forecast.bot``."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import hydra
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from sports_forecast.bot.dispatcher import build_dispatcher, register_commands
from sports_forecast.bot.heartbeat import write_heartbeat
from sports_forecast.bot.notifications import (
    notification_poll_loop,
    validate_notification_destinations,
)
from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)


def _merge_env_lists(cfg: DictConfig, key: str, env_name: str) -> None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return
    ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
    if ids:
        OmegaConf.update(cfg, key, ids)


async def _heartbeat_loop(bot, api_url: str, path: Path) -> None:
    """Периодически проверять Telegram и internal API без записи их ответов."""
    while True:
        telegram_ok = internal_api_ok = False
        try:
            await bot.get_me()
            telegram_ok = True
        except Exception:
            logger.warning("Heartbeat: Telegram API недоступен")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{api_url.rstrip('/')}/health")
            internal_api_ok = response.status_code == 200
        except httpx.HTTPError:
            logger.warning("Heartbeat: internal API недоступен")
        write_heartbeat(path, telegram_ok=telegram_ok, internal_api_ok=internal_api_ok)
        await asyncio.sleep(30)


async def _async_main(cfg: DictConfig, token: str) -> None:
    notifications_enabled = bool(str(cfg.bot.get("control_api_key_file") or "").strip())
    if notifications_enabled:
        validate_notification_destinations(cfg)
    bot, dp = build_dispatcher(cfg, token)
    api_url = str(cfg.bot.api_base_url)
    heartbeat_path = Path(os.getenv("SF_BOT_HEARTBEAT_PATH", "/tmp/sf-bot-heartbeat.json"))
    heartbeat = asyncio.create_task(_heartbeat_loop(bot, api_url, heartbeat_path))
    notification_poller = None
    if notifications_enabled:
        notification_poller = asyncio.create_task(
            notification_poll_loop(
                cfg,
                bot,
                interval_seconds=float(cfg.bot.get("notification_poll_interval_seconds", 10)),
            )
        )
    try:
        await register_commands(bot, cfg)
        await dp.start_polling(bot)
    finally:
        heartbeat.cancel()
        if notification_poller is not None:
            notification_poller.cancel()
            await asyncio.gather(notification_poller, return_exceptions=True)
        await bot.session.close()


def _load_notification_destinations(cfg: DictConfig) -> None:
    """Загрузить alias map из защищённого runtime JSON-файла, если он задан."""
    raw_path = str(cfg.bot.get("notification_destinations_file") or "").strip()
    if not raw_path:
        return
    try:
        destinations = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось прочитать notification destinations file") from exc
    if not isinstance(destinations, dict):
        raise ValueError("Notification destinations file должен содержать JSON object")
    OmegaConf.update(cfg, "bot.notification_destinations", destinations, force_add=True)


@hydra.main(version_base="1.3", config_path="../../conf", config_name="bot")
def main(cfg: DictConfig) -> None:
    """Запуск long-polling (MVP)."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    configure_logging(cfg.get("logging", {}).get("level", "INFO"))
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Нужна переменная окружения BOT_TOKEN")

    _merge_env_lists(cfg, "bot.allowed_user_ids", "BOT_ALLOWED_USER_IDS")
    _merge_env_lists(cfg, "bot.admin_user_ids", "BOT_ADMIN_USER_IDS")
    api_url = os.getenv("BOT_API_BASE_URL", "").strip()
    if api_url:
        OmegaConf.update(cfg, "bot.api_base_url", api_url)
    control_api_key_file = os.getenv("BOT_CONTROL_API_KEY_FILE", "").strip()
    if control_api_key_file:
        OmegaConf.update(cfg, "bot.control_api_key_file", control_api_key_file)
    notification_destinations_file = os.getenv("BOT_NOTIFICATION_DESTINATIONS_FILE", "").strip()
    if notification_destinations_file:
        OmegaConf.update(
            cfg,
            "bot.notification_destinations_file",
            notification_destinations_file,
            force_add=True,
        )
    _load_notification_destinations(cfg)

    asyncio.run(_async_main(cfg, token))


if __name__ == "__main__":
    main()
