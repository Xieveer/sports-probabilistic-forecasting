"""Точка входа: ``python -m sports_forecast.bot``."""

from __future__ import annotations

import asyncio
import os

import hydra
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from sports_forecast.bot.dispatcher import build_dispatcher
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


async def _async_main(cfg: DictConfig, token: str) -> None:
    bot, dp = build_dispatcher(cfg, token)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


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

    asyncio.run(_async_main(cfg, token))


if __name__ == "__main__":
    main()
