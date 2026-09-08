"""Контракт file-backed database URL для всех DB entry points."""

from __future__ import annotations

import pytest

from sports_forecast.service.db.engine import get_database_url


def test_database_url_file_has_priority_over_environment(monkeypatch, tmp_path) -> None:
    """Bootstrap/API/Worker используют URL из runtime secret file."""
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://file-user:file-secret@db/app\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unexpected.db")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    assert get_database_url() == "postgresql://file-user:file-secret@db/app"


def test_database_url_file_rejects_empty_secret(monkeypatch, tmp_path) -> None:
    """Пустой secret не даёт bootstrap молча перейти на SQLite."""
    secret = tmp_path / "database_url"
    secret.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    with pytest.raises(ValueError, match="DATABASE_URL_FILE"):
        get_database_url()


def test_database_url_file_rejects_unavailable_secret(monkeypatch, tmp_path) -> None:
    """Отсутствующий secret не разрешает неявный SQLite fallback."""
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "missing"))

    with pytest.raises(ValueError, match="DATABASE_URL_FILE"):
        get_database_url()
