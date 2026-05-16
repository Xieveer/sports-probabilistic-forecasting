"""Регрессии R41: лёгкий путь Telegram не триггерит Airflow."""

from __future__ import annotations

import inspect

from sports_forecast.bot.handlers import predict


def test_predict_upcoming_url_is_api_only_no_airflow() -> None:
    u = predict._predict_upcoming_url("http://api:8000/", " nhl ")
    assert u == "http://api:8000/predict/upcoming/nhl"
    assert "airflow" not in u.casefold()


def test_edge_command_uses_live_path_fetch_predict_upcoming_only() -> None:
    src = inspect.getsource(predict.cmd_edge)
    assert "fetch_predict_upcoming" in src
    assert "api/v1/dags" not in src


def test_edge_callback_matches_light_contract() -> None:
    src = inspect.getsource(predict.cb_edge)
    assert "fetch_predict_upcoming" in src
    assert "api/v1/dags" not in src


def test_cmd_refresh_still_posts_to_airflow() -> None:
    from sports_forecast.bot.handlers import admin

    src = inspect.getsource(admin.cmd_refresh)
    assert "api/v1/dags/" in src
    assert '.post("' in src or ".post(url" in src or "client.post" in src
