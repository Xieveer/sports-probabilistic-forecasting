"""Регрессии R41: лёгкий путь Telegram не триггерит Airflow."""

from __future__ import annotations

import inspect

from sports_forecast.bot.handlers import predict


def test_predict_upcoming_url_is_api_only_no_airflow() -> None:
    u = predict._predict_upcoming_url("http://api:8000/", " nhl ")
    assert u == "http://api:8000/predict/upcoming/nhl"
    assert "airflow" not in u.casefold()


def test_predict_command_uses_live_path_fetch_predict_upcoming_only() -> None:
    src = inspect.getsource(predict.cb_predict_period)
    assert "fetch_predict_upcoming" in src
    assert "api/v1/dags" not in src


def test_edge_handler_is_removed() -> None:
    assert not hasattr(predict, "cmd_edge")
    assert not hasattr(predict, "cb_edge")


def test_cmd_refresh_uses_data_cycle_control_api() -> None:
    from sports_forecast.bot.handlers import admin

    src = inspect.getsource(admin.cmd_refresh)
    assert "_request_manual_cycle" in src
    assert "airflow" not in src.casefold()
