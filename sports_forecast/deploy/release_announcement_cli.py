"""Однократное сообщение владельцу после успешного production acceptance."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import yaml
from aiogram import Bot

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_NOTES_PATH = Path(__file__).resolve().parents[2] / "conf" / "release-notes.yaml"


def format_release_announcement(version: str, changes: list[str]) -> str:
    """Сформировать короткое сообщение о выпущенной версии."""
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("Некорректная версия")
    if not 1 <= len(changes) <= 6 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 150 for item in changes
    ):
        raise ValueError("Некорректный список изменений")
    return "\n".join(
        [f"Запущена версия {version}", "Кратко об изменениях:"]
        + [f"• {item.strip()}" for item in changes]
    )


async def _send(token: str, owner_id: int, message: str) -> None:
    """Отправить сообщение в личный чат владельца и закрыть HTTP-сессию."""
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=owner_id, text=message)
    finally:
        await bot.session.close()


def main() -> int:
    """Отправить объявление только при совпадении образа и release notes."""
    try:
        version = os.environ["SF_APP_VERSION"]
        notes = yaml.safe_load(_NOTES_PATH.read_text(encoding="utf-8"))
        if not isinstance(notes, dict) or notes.get("version") != version:
            raise ValueError("Release notes не соответствуют установленной версии")
        message = format_release_announcement(version, notes.get("changes"))
        owner = os.environ["BOT_BETS_OWNER_ID"].strip()
        if not owner.isdigit():
            raise ValueError("Владелец не настроен")
        token = Path(os.environ["BOT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("Telegram token отсутствует")
        asyncio.run(_send(token, int(owner), message))
    except Exception:
        logger.error("Не удалось отправить сообщение о новой версии")
        return 1
    logger.info("Сообщение о новой версии отправлено владельцу")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
