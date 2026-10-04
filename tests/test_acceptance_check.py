from unittest.mock import MagicMock, patch

from scripts.acceptance_check import _check_bot, _check_docs, check


def test_acceptance_check_is_read_only_and_checks_release_contract() -> None:
    with (
        patch("scripts.acceptance_check.httpx.Client") as client_type,
        patch("scripts.acceptance_check.create_engine") as create_engine,
        patch("scripts.acceptance_check.subprocess.run") as run,
    ):
        client = MagicMock()
        client.__enter__.return_value = client
        client_type.return_value = client
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
            "status": "succeeded",
            "predictions_count": 1,
        }
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        create_engine.return_value = engine
        run.return_value = MagicMock(returncode=0)
        client.get.side_effect = (
            MagicMock(status_code=200, json=lambda: {"status": "ok"}),
            MagicMock(
                status_code=200,
                json=lambda: {"status": "ok", "db_connected": True, "version": "1.0.0"},
            ),
            MagicMock(
                status_code=200,
                headers={"content-type": "text/html"},
                json=MagicMock(side_effect=ValueError("not json")),
            ),
            MagicMock(status_code=200, json=lambda: {"info": {"version": "1.0.0"}}),
            MagicMock(
                status_code=200,
                json=lambda: {"model": {"version": "model-20260809"}},
            ),
        )
        assert (
            check(
                "http://api",
                prediction_path="/predict/known?live_pinnacle=false",
                expected_app_version="1.0.0",
                expected_model_version="model-20260809",
                database_url="postgresql://readonly",
                worker_run_id="daily-2026-08-09",
                bot_health_command=("bot-health",),
            )
            == []
        )
    assert [call.args[0] for call in client.get.call_args_list] == [
        "http://api/health",
        "http://api/ready",
        "http://api/docs",
        "http://api/openapi.json",
        "http://api/predict/known?live_pinnacle=false",
    ]
    assert all(call.args == () for call in client.post.call_args_list)


def test_acceptance_check_reports_bad_model_and_worker_without_payloads() -> None:
    with (
        patch("scripts.acceptance_check.httpx.Client") as client_type,
        patch("scripts.acceptance_check.create_engine") as create_engine,
        patch("scripts.acceptance_check.subprocess.run") as run,
    ):
        client = MagicMock()
        client.__enter__.return_value = client
        client_type.return_value = client
        client.get.side_effect = (
            MagicMock(status_code=200, json=lambda: {"status": "ok"}),
            MagicMock(
                status_code=200,
                json=lambda: {"status": "ok", "db_connected": True, "version": "1.0.0"},
            ),
            MagicMock(
                status_code=200,
                headers={"content-type": "text/html"},
                json=MagicMock(side_effect=ValueError("not json")),
            ),
            MagicMock(status_code=200, json=lambda: {"info": {"version": "1.0.0"}}),
            MagicMock(status_code=200, json=lambda: {"model": {"version": "unexpected"}}),
        )
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
            "status": "failed",
            "predictions_count": 0,
        }
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        create_engine.return_value = engine
        run.return_value = MagicMock(returncode=1)

        errors = check(
            "http://api",
            prediction_path="/predict/known?live_pinnacle=false",
            expected_app_version="1.0.0",
            expected_model_version="expected",
            database_url="postgresql://readonly",
            worker_run_id="daily-2026-08-09",
            bot_health_command=("bot-health",),
        )

    assert "prediction: version модели не совпадает" in errors
    assert "worker: последний запуск не завершился успешно" in errors
    assert "bot: heartbeat не подтверждает доступность" in errors


def test_acceptance_check_rejects_empty_bot_health_command() -> None:
    """Неполный operator environment завершает acceptance ошибкой, а не traceback."""
    errors: list[str] = []

    _check_bot((), errors)

    assert errors == ["bot: heartbeat command не задана"]


def test_acceptance_check_rejects_non_html_docs_without_parsing_payload() -> None:
    """Статус 200 с неправильным media type не подтверждает Swagger UI."""
    client = MagicMock()
    client.get.return_value = MagicMock(
        status_code=200,
        headers={"content-type": "application/json"},
        json=MagicMock(side_effect=AssertionError("payload must not be parsed")),
    )
    errors: list[str] = []

    _check_docs(client, "http://api/docs", errors)

    assert errors == ["docs: ожидался HTML"]
