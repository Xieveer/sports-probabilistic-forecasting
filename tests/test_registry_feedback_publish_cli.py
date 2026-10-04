"""CLI server feedback publisher: credentials, database and bounded commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sports_forecast.deploy import registry_feedback_publish_cli as cli
from sports_forecast.deploy.registry_publish import RegistryStorageError


def test_database_requires_explicit_postgres_url_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://inline-user:inline-secret@db/app")
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)

    with pytest.raises(cli.RegistryFeedbackCliError, match="DATABASE_URL_FILE"):
        cli._database_url_from_environment()

    url_file = tmp_path / "database-url"
    url_file.write_text("sqlite:///not-allowed.db\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(url_file))
    with pytest.raises(cli.RegistryFeedbackCliError, match="PostgreSQL"):
        cli._database_url_from_environment()


def test_database_reads_postgres_url_from_file_without_echoing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url_file = tmp_path / "database-url"
    url_file.write_text(
        "postgresql+psycopg://service:private-value@db.example/app\n", encoding="utf-8"
    )
    monkeypatch.setenv("DATABASE_URL_FILE", str(url_file))

    assert (
        cli._database_url_from_environment()
        == "postgresql+psycopg://service:private-value@db.example/app"
    )


def test_cli_fails_closed_without_database_file_and_hides_direct_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://service:private-value@db.example/app")

    assert cli.main(["publish"]) == 1
    error = caplog.text
    assert "DATABASE_URL_FILE" not in error
    assert "private-value" not in error
    assert "RegistryFeedbackCliError" in error


def test_feedback_storage_uses_server_scoped_credentials_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeStorage:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(cli, "Boto3RegistryStorage", FakeStorage)
    monkeypatch.setenv("SF_OBJECT_STORAGE_ENDPOINT", "https://objects.example")
    monkeypatch.setenv("SF_OBJECT_STORAGE_BUCKET", "registry")
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_ACCESS_KEY_ID", "server-id")
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY", "server-secret")
    monkeypatch.setenv("SF_OBJECT_STORAGE_ACCESS_KEY_ID", "broad-publisher-id")
    monkeypatch.setenv("SF_OBJECT_STORAGE_SECRET_ACCESS_KEY", "broad-publisher-secret")

    cli._feedback_storage_from_environment()

    assert captured["access_key_id"] == "server-id"
    assert captured["secret_access_key"] == "server-secret"
    assert captured["bucket"] == "registry"


def test_feedback_storage_secret_file_support_and_mismatch_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "access"
    secret_file = tmp_path / "secret"
    key_file.write_text("server-id\n", encoding="utf-8")
    secret_file.write_text("server-secret\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    class FakeStorage:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(cli, "Boto3RegistryStorage", FakeStorage)
    monkeypatch.setenv("SF_OBJECT_STORAGE_ENDPOINT", "https://objects.example")
    monkeypatch.setenv("SF_OBJECT_STORAGE_BUCKET", "registry")
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_ACCESS_KEY_ID_FILE", str(key_file))
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY_FILE", str(secret_file))
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_ACCESS_KEY_ID", "server-id")
    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY", "server-secret")

    cli._feedback_storage_from_environment()
    assert captured["secret_access_key"] == "server-secret"

    monkeypatch.setenv("SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY", "different-secret")
    with pytest.raises(RegistryStorageError) as error:
        cli._feedback_storage_from_environment()
    assert "different-secret" not in str(error.value)


def test_publish_command_has_explicit_batch_limit_and_safe_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_url = tmp_path / "db-url"
    database_url.write_text("postgresql://service:secret@db/app", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(database_url))
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(cli, "_feedback_storage_from_environment", lambda: object())
    monkeypatch.setattr(cli, "create_engine", lambda *_args, **_kwargs: _FakeEngine())
    monkeypatch.setattr(cli, "Session", lambda _engine: _FakeSession())
    publisher = _FakePublisher()
    monkeypatch.setattr(cli, "RegistryCandidateFeedback", lambda *_args, **_kwargs: publisher)

    result = cli.main(["publish", "--max-batches", "2"])

    assert result == 0
    assert publisher.publish_calls == 2
    output = capsys.readouterr().out
    assert '"published_batches": 2' in output
    assert "secret" not in output


def test_collect_ack_command_passes_bounded_batch_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_url = tmp_path / "db-url"
    database_url.write_text("postgresql://service:secret@db/app", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(database_url))
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(cli, "_feedback_storage_from_environment", lambda: object())
    monkeypatch.setattr(cli, "create_engine", lambda *_args, **_kwargs: _FakeEngine())
    monkeypatch.setattr(cli, "Session", lambda _engine: _FakeSession())
    publisher = _FakePublisher()
    monkeypatch.setattr(cli, "RegistryCandidateFeedback", lambda *_args, **_kwargs: publisher)

    result = cli.main(["collect-acks", "--max-batches", "7"])

    assert result == 0
    assert publisher.ack_limit == 7
    assert '"acknowledged_batches": 3' in capsys.readouterr().out


def test_parser_rejects_unbounded_limits() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["publish", "--max-batches", "101"])
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["collect-acks", "--max-batches", "0"])


class _FakeEngine:
    def dispose(self) -> None:
        pass


class _FakeSession:
    def __init__(self) -> None:
        self.value = object()

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, *_args: object) -> None:
        pass


class _FakePublisher:
    def __init__(self) -> None:
        self.publish_calls = 0
        self.ack_limit: int | None = None

    def publish_next_batch(self) -> str | None:
        self.publish_calls += 1
        return f"0000000000000000000{self.publish_calls}-batch" if self.publish_calls <= 2 else None

    def collect_acknowledgements(self, *, max_batches: int = 100) -> int:
        self.ack_limit = max_batches
        return 3
