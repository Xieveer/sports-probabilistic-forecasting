"""Проверки явной настройки логирования после раннего импорта модулей."""

from __future__ import annotations

import logging

from sports_forecast.utils import log_config


def test_explicit_level_applies_after_early_get_logger(monkeypatch) -> None:
    """Ранний логгер не должен блокировать уровень из Hydra-конфигурации."""
    root = logging.Logger("isolated-root")
    monkeypatch.setattr(log_config, "_LOG_CONFIGURED", False)
    monkeypatch.setattr(log_config.logging, "getLogger", lambda _name=None: root)

    log_config.get_logger("early-module")
    first_handler = root.handlers[0]
    log_config.configure_logging(level="DEBUG")

    assert root.level == logging.DEBUG
    assert root.handlers == [first_handler]
