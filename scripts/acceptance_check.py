"""Non-mutating acceptance-проверка уже запущенного production-кандидата."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from collections.abc import Sequence

import httpx
from sqlalchemy import create_engine, text


def _get_json(
    client: httpx.Client, url: str, *, label: str, errors: list[str]
) -> dict[str, object] | None:
    """Получить JSON без вывода response payload в stdout или error message."""
    try:
        response = client.get(url)
        if response.status_code != 200:
            errors.append(f"{label}: HTTP {response.status_code}")
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        errors.append(f"{label}: недоступен")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label}: некорректный JSON")
        return None
    return payload


def _check_worker(database_url: str, run_id: str, errors: list[str]) -> None:
    """Прочитать safe summary последнего Worker запуска без изменения БД."""
    try:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT status, predictions_count FROM worker_executions "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .one_or_none()
            )
        engine.dispose()
    except Exception:
        errors.append("worker: safe execution state недоступен")
        return
    if row is None:
        errors.append("worker: последний запуск не найден")
    elif row["status"] != "succeeded" or int(row["predictions_count"] or 0) <= 0:
        errors.append("worker: последний запуск не завершился успешно")


def _check_bot(command: Sequence[str], errors: list[str]) -> None:
    """Проверить freshness безопасного bot heartbeat через read-only health command."""
    if not command:
        errors.append("bot: heartbeat command не задана")
        return
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        errors.append("bot: heartbeat command недоступна")
        return
    if completed.returncode != 0:
        errors.append("bot: heartbeat не подтверждает доступность")


def check(
    base_url: str,
    *,
    prediction_path: str,
    expected_app_version: str,
    expected_model_version: str,
    database_url: str,
    worker_run_id: str,
    bot_health_command: Sequence[str],
) -> list[str]:
    """Проверить read-only release-инварианты уже запущенного контура.

    Команда использует исключительно HTTP GET, SELECT и healthcheck bot. Она не
    запускает Worker/training, не отправляет сообщения и не печатает payloads.
    """
    errors: list[str] = []
    normalized_base_url = base_url.rstrip("/")
    with httpx.Client(timeout=5.0) as client:
        health = _get_json(client, f"{normalized_base_url}/health", label="health", errors=errors)
        ready = _get_json(client, f"{normalized_base_url}/ready", label="ready", errors=errors)
        _get_json(client, f"{normalized_base_url}/docs", label="docs", errors=errors)
        prediction = _get_json(
            client,
            f"{normalized_base_url}/{prediction_path.lstrip('/')}",
            label="prediction",
            errors=errors,
        )

    if health is not None and health.get("status") != "ok":
        errors.append("health: liveness не подтверждён")
    if ready is not None:
        if ready.get("status") != "ok" or ready.get("db_connected") is not True:
            errors.append("ready: PostgreSQL не подтверждена")
        if ready.get("version") != expected_app_version:
            errors.append("ready: версия API не совпадает")
    if prediction is not None:
        model = prediction.get("model")
        if not isinstance(model, dict) or model.get("version") != expected_model_version:
            errors.append("prediction: version модели не совпадает")

    _check_worker(database_url, worker_run_id, errors)
    _check_bot(bot_health_command, errors)
    return errors


def main() -> int:
    """Запустить acceptance и вернуть shell exit code без mutation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--prediction-path", required=True)
    parser.add_argument("--expected-app-version", required=True)
    parser.add_argument("--expected-model-version", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--worker-run-id", required=True)
    parser.add_argument("--bot-health-command", required=True)
    args = parser.parse_args()
    errors = check(
        args.base_url,
        prediction_path=args.prediction_path,
        expected_app_version=args.expected_app_version,
        expected_model_version=args.expected_model_version,
        database_url=args.database_url,
        worker_run_id=args.worker_run_id,
        bot_health_command=tuple(shlex.split(args.bot_health_command)),
    )
    for error in errors:
        print(error)  # noqa: T201
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
