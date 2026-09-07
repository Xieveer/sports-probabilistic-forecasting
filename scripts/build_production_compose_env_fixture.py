"""Создать безопасный env fixture для rendered production Compose gate."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Mapping
from pathlib import Path


def build_fixture(
    path: Path,
    *,
    root: Path,
    app_version: str,
    image_refs: Mapping[str, str] | None = None,
) -> None:
    """Записать все обязательные Compose variables без production secrets."""
    digest = "sha256:" + "0" * 64
    secret_root = root / "secrets"
    secret_root.mkdir(parents=True, exist_ok=True)
    secret_values = {
        "postgres_password": "fixture-postgres-password",
        "api_db_password": "fixture-api-password",
        "worker_db_password": "fixture-worker-password",
        "migrator_db_password": "fixture-migrator-password",
        "api_database_url": "postgresql://sf_api_reader:fixture-api-password@db:5432/sports_forecast",
        "worker_database_url": "postgresql://sf_refresh_writer:fixture-worker-password@db:5432/sports_forecast",
        "migrator_database_url": "postgresql://sf_migrator:fixture-migrator-password@db:5432/sports_forecast",
        "owner_database_url": "postgresql://sf_user:fixture-postgres-password@db:5432/sports_forecast",
        "bot_token": "123456:fixture_test_token_for_local_contract",
        "object_storage_access_key": "fixture-access-key",
        "object_storage_secret_key": "fixture-secret-key",
        "odds_api_key_free": "fixture-odds-free",
        "odds_api_key_20k": "fixture-odds-20k",
        "odds_api_key_100k": "fixture-odds-100k",
        "odds_api_key": "fixture-odds-legacy",
    }
    for name, value in secret_values.items():
        secret_path = secret_root / name
        secret_path.write_text(value, encoding="utf-8")
        # Local Compose bind-secrets сохраняют host mode; fixture должен быть
        # читаем numeric runtime user. Реальные secret files имеют 0400/10001.
        secret_path.chmod(0o644)
    default_images = {
        "SF_POSTGRES_IMAGE": f"postgres@{digest}",
        "SF_API_IMAGE": f"ghcr.io/fixture/api@{digest}",
        "SF_WORKER_IMAGE": f"ghcr.io/fixture/worker@{digest}",
        "SF_BOT_IMAGE": f"ghcr.io/fixture/bot@{digest}",
        "SF_ARCHIVE_SYNC_IMAGE": f"ghcr.io/fixture/archive-sync@{digest}",
    }
    if image_refs is not None:
        missing = set(default_images) - set(image_refs)
        if missing or any("@sha256:" not in value for value in image_refs.values()):
            raise ValueError("image_refs должны содержать digest для каждого runtime image")
        default_images.update(image_refs)
    values = {
        "SF_WORKER_RUN_ID": "fixture-run-id",
        "SF_APP_VERSION": app_version,
        "SF_MODEL_RUNTIME_ROOT": str(root / "runtime_models"),
        "SF_CANONICAL_SOURCE_ROOT": str(root / "source" / "nhl"),
        "SF_OPERATIONAL_ARCHIVE_ROOT": str(root / "archive"),
        "SF_ARCHIVE_SYNC_STATE_ROOT": str(root / "sync-state"),
        "SF_POSTGRES_PASSWORD_FILE": str(secret_root / "postgres_password"),
        "SF_API_DB_PASSWORD_FILE": str(secret_root / "api_db_password"),
        "SF_WORKER_DB_PASSWORD_FILE": str(secret_root / "worker_db_password"),
        "SF_MIGRATOR_DB_PASSWORD_FILE": str(secret_root / "migrator_db_password"),
        "SF_API_DATABASE_URL_FILE": str(secret_root / "api_database_url"),
        "SF_WORKER_DATABASE_URL_FILE": str(secret_root / "worker_database_url"),
        "SF_MIGRATOR_DATABASE_URL_FILE": str(secret_root / "migrator_database_url"),
        "SF_OWNER_DATABASE_URL_FILE": str(secret_root / "owner_database_url"),
        "SF_BOT_TOKEN_FILE": str(secret_root / "bot_token"),
        "SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE": str(secret_root / "object_storage_access_key"),
        "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE": str(secret_root / "object_storage_secret_key"),
        "ODDS_API_KEY_FREE_FILE": str(secret_root / "odds_api_key_free"),
        "ODDS_API_KEY_20K_FILE": str(secret_root / "odds_api_key_20k"),
        "ODDS_API_KEY_100K_FILE": str(secret_root / "odds_api_key_100k"),
        "ODDS_API_KEY_FILE": str(secret_root / "odds_api_key"),
        "BOT_TELEGRAM_API_BASE_URL": "http://telegram-test:8081",
        "BOT_ALLOWED_USER_IDS": "1",
        "SF_OBJECT_STORAGE_ENDPOINT": "https://storage.example.invalid",
        "SF_OBJECT_STORAGE_BUCKET": "fixture-bucket",
        **default_images,
    }
    for directory in ("runtime_models", "source", "archive", "sync-state"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def main() -> None:
    """Создать fixture по CLI arguments."""
    parser = ArgumentParser(description="Безопасный env fixture production Compose")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    parser.add_argument("--postgres-image")
    parser.add_argument("--api-image")
    parser.add_argument("--worker-image")
    parser.add_argument("--bot-image")
    parser.add_argument("--archive-sync-image")
    args = parser.parse_args()
    supplied_images = {
        "SF_POSTGRES_IMAGE": args.postgres_image,
        "SF_API_IMAGE": args.api_image,
        "SF_WORKER_IMAGE": args.worker_image,
        "SF_BOT_IMAGE": args.bot_image,
        "SF_ARCHIVE_SYNC_IMAGE": args.archive_sync_image,
    }
    build_fixture(
        args.output,
        root=args.root,
        app_version=args.app_version,
        image_refs=supplied_images if all(supplied_images.values()) else None,
    )


if __name__ == "__main__":
    main()
