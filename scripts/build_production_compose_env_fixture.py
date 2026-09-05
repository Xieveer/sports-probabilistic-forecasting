"""Создать безопасный env fixture для rendered production Compose gate."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path


def build_fixture(path: Path, *, root: Path, app_version: str) -> None:
    """Записать все обязательные Compose variables без production secrets."""
    digest = "sha256:" + "0" * 64
    values = {
        "POSTGRES_PASSWORD": "fixture-postgres-password",
        "SF_API_DATABASE_URL": "postgresql://fixture:fixture@db:5432/sports_forecast",
        "SF_WORKER_DATABASE_URL": "postgresql://fixture:fixture@db:5432/sports_forecast",
        "BOT_TOKEN": "fixture-bot-token",
        "SF_WORKER_RUN_ID": "fixture-run-id",
        "SF_APP_VERSION": app_version,
        "SF_MODEL_RUNTIME_ROOT": str(root / "runtime_models"),
        "SF_CANONICAL_SOURCE_ROOT": str(root / "source"),
        "SF_OPERATIONAL_ARCHIVE_ROOT": str(root / "archive"),
        "SF_ARCHIVE_SYNC_STATE_ROOT": str(root / "sync-state"),
        "SF_OBJECT_STORAGE_ENDPOINT": "https://storage.example.invalid",
        "SF_OBJECT_STORAGE_BUCKET": "fixture-bucket",
        "SF_OBJECT_STORAGE_ACCESS_KEY_ID": "fixture-access-key",
        "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY": "fixture-secret-key",
        "SF_POSTGRES_IMAGE": f"postgres@{digest}",
        "SF_API_IMAGE": f"ghcr.io/fixture/api@{digest}",
        "SF_WORKER_IMAGE": f"ghcr.io/fixture/worker@{digest}",
        "SF_BOT_IMAGE": f"ghcr.io/fixture/bot@{digest}",
        "SF_ARCHIVE_SYNC_IMAGE": f"ghcr.io/fixture/archive-sync@{digest}",
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
    args = parser.parse_args()
    build_fixture(args.output, root=args.root, app_version=args.app_version)


if __name__ == "__main__":
    main()
