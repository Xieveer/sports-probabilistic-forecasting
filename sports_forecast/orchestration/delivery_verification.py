"""Явная однократная проверка первой Telegram-доставки после rollout."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from typing import Any

from sports_forecast.orchestration.telegram_http import telegram_send_message
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class DeliveryVerificationError(RuntimeError):
    """Telegram не подтвердил контролируемую доставку."""


TelegramSender = Callable[..., dict[str, Any]]


def build_delivery_verification_text(*, release_image: str, model_version: str) -> str:
    """Собрать распознаваемый, не содержащий секретов текст проверки.

    Args:
        release_image: Immutable image reference с digest опубликованного release.
        model_version: Immutable identity активной модели.

    Returns:
        Текст единственного контролируемого сообщения владельцу.
    """
    return (
        "Sports Forecast: проверка первой доставки.\n"
        f"Release image: {release_image}\n"
        f"Model: {model_version}\n"
        "Это однократное операторское сообщение, не прогноз и не регулярный digest."
    )


def run_delivery_verification(
    *,
    token: str,
    recipient_chat_id: str,
    release_image: str,
    model_version: str,
    sender: TelegramSender = telegram_send_message,
) -> None:
    """Отправить ровно одно сообщение и проверить ``ok`` Telegram API.

    Args:
        token: Секретный токен Telegram-бота.
        recipient_chat_id: Один секретно-конфигурируемый Telegram chat ID.
        release_image: Immutable image reference с digest опубликованного release.
        model_version: Immutable identity активной модели.
        sender: Узкий Telegram transport для тестирования и отправки.

    Raises:
        ValueError: Если обязательный input пуст.
        DeliveryVerificationError: Если Telegram не подтвердил доставку.
        Exception: Ошибка transport пробрасывается вызывающему коду без логирования секретов.
    """
    if not token.strip():
        raise ValueError("Нужен BOT_TOKEN")
    if not recipient_chat_id.strip():
        raise ValueError("Нужен SF_DELIVERY_VERIFICATION_CHAT_ID")
    if not release_image.strip() or not model_version.strip():
        raise ValueError("Нужны release image и model version")

    response = sender(
        token=token,
        chat_id=recipient_chat_id,
        text=build_delivery_verification_text(
            release_image=release_image,
            model_version=model_version,
        ),
    )
    if response.get("ok") is not True:
        raise DeliveryVerificationError("Telegram не подтвердил доставку")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Однократно подтвердить Telegram-доставку после production acceptance."
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Явно разрешить ровно одну внешнюю Telegram-отправку.",
    )
    parser.add_argument(
        "--release-image", required=True, help="Immutable image reference с digest."
    )
    parser.add_argument(
        "--model-version", required=True, help="Immutable identity активной модели."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Запустить opt-in delivery verification без повторов и без scheduler."""
    args = _parse_args(argv)
    if not args.send:
        print("Контролируемая отправка не выполнена: требуется --send.")  # noqa: T201
        return 2

    try:
        run_delivery_verification(
            token=os.environ.get("BOT_TOKEN", ""),
            recipient_chat_id=os.environ.get("SF_DELIVERY_VERIFICATION_CHAT_ID", ""),
            release_image=args.release_image,
            model_version=args.model_version,
            sender=telegram_send_message,
        )
    except DeliveryVerificationError:
        logger.error("Telegram не подтвердил проверочную доставку")
        print("Контролируемая доставка не доставлена.")  # noqa: T201
        return 1
    except (OSError, ValueError):
        logger.error("Контролируемая проверка доставки не выполнена")
        print("Контролируемая доставка не выполнена.")  # noqa: T201
        return 1

    print(  # noqa: T201
        "Контролируемая доставка подтверждена: "
        f"release={args.release_image}, model={args.model_version}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DeliveryVerificationError",
    "build_delivery_verification_text",
    "main",
    "run_delivery_verification",
]
