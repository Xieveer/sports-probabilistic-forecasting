"""Админ-команды: здоровье API, триггер Airflow, список каталогов моделей."""

from __future__ import annotations

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from omegaconf import DictConfig

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

router = Router(name="admin")


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


@router.message(Command("status"))
async def cmd_status(message: Message, cfg: DictConfig) -> None:
    """Проверка /health FastAPI."""
    uid = message.from_user.id if message.from_user else 0
    admins = {int(x) for x in (cfg.bot.get("admin_user_ids") or []) if x is not None}
    if not _is_admin(uid, admins):
        await message.answer("Команда только для администратора.")
        return
    base = str(cfg.bot.api_base_url).rstrip("/")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{base}/health", timeout=30.0)
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            await message.answer(f"Health: ошибка {e}")
            return
    await message.answer(f"API: {body}")


@router.message(Command("refresh"))
async def cmd_refresh(message: Message, cfg: DictConfig) -> None:
    """Триггер DAG data_refresh через Airflow REST (если задан airflow_base_url)."""
    uid = message.from_user.id if message.from_user else 0
    admins = {int(x) for x in (cfg.bot.get("admin_user_ids") or []) if x is not None}
    if not _is_admin(uid, admins):
        await message.answer("Команда только для администратора.")
        return
    parts = (message.text or "").split(maxsplit=1)
    tournament = parts[1].strip() if len(parts) > 1 else ""
    ab = str(cfg.bot.get("airflow_base_url") or "").rstrip("/")
    if not ab:
        await message.answer("Airflow URL не настроен (bot.airflow_base_url).")
        return
    dag_id = str(cfg.bot.get("airflow_dag_id") or "data_refresh")
    user = str(cfg.bot.get("airflow_username") or "")
    password = str(cfg.bot.get("airflow_password") or "")
    url = f"{ab}/api/v1/dags/{dag_id}/dagRuns"
    payload: dict = {"conf": {}}
    if tournament:
        payload["conf"]["tournaments"] = tournament
    auth = (user, password) if user and password else None
    async with httpx.AsyncClient(auth=auth) as client:
        try:
            r = await client.post(url, json=payload, timeout=60.0)
            r.raise_for_status()
        except Exception as e:
            logger.exception("airflow trigger failed")
            await message.answer(f"Airflow: {e}")
            return
    await message.answer(f"DAG {dag_id} запущен (conf tournaments={tournament or 'default'})")


@router.message(Command("models"))
async def cmd_models(message: Message, cfg: DictConfig) -> None:
    """Список каталогов под ``models/`` (локально на хосте бота)."""
    uid = message.from_user.id if message.from_user else 0
    admins = {int(x) for x in (cfg.bot.get("admin_user_ids") or []) if x is not None}
    if not _is_admin(uid, admins):
        await message.answer("Команда только для администратора.")
        return
    root = PROJECT_ROOT / "models"
    if not root.is_dir():
        await message.answer("Каталог models/ не найден.")
        return
    names = sorted(p.name for p in root.iterdir() if p.is_dir())
    text = "\n".join(names[:80]) if names else "(пусто)"
    await message.answer(f"models/:\n{text}")
