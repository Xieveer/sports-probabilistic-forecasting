"""Командная точка входа локального review UI."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.review_app import create_review_app
from sports_forecast.identity.review_service import ReviewQueueService


def main() -> None:
    """Запустить интерфейс только на loopback после явной миграции registry."""
    parser = argparse.ArgumentParser(description="Локальная очередь подтверждения сущностей")
    parser.add_argument(
        "--registry", required=True, type=Path, help="Путь к инициализированному registry SQLite"
    )
    parser.add_argument(
        "--secret-file", required=True, type=Path, help="Путь к secret file с правами 0600"
    )
    parser.add_argument("--actor", default="owner", help="Имя владельца для аудита")
    args = parser.parse_args()
    registry = EntityRegistry(args.registry)
    with registry._connect(write=False):
        pass
    app = create_review_app(
        ReviewQueueService(registry), secret_path=args.secret_file, actor=args.actor
    )
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
