"""Единый доступ к версии поставляемого пакета."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


PACKAGE_NAME = "sports-probabilistic-forecasting"


def get_service_version() -> str:
    """Вернуть версию установленного пакета без дублирования с ``pyproject.toml``."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"
