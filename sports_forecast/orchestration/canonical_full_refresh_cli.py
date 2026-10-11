"""CLI bounded canonical full-refresh job для scheduler runtime."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import hydra
from omegaconf import DictConfig

from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)


@hydra.main(config_path="../../conf", config_name="config", version_base="1.3")
def main(cfg: DictConfig) -> None:
    """Запустить один refresh из scheduler-safe environment inputs."""
    configure_logging(level=cfg.logging.level)
    prepared_archive_root = Path(os.environ["SF_OPERATIONAL_ARCHIVE_ROOT"])
    result = run_full_refresh(
        cfg,
        run_id=os.environ["SF_WORKER_RUN_ID"],
        runtime_root=Path(os.environ["SF_MODEL_RUNTIME_ROOT"]),
        app_version=os.environ["SF_APP_VERSION"],
        refreshed_at=datetime.now(UTC),
        prepared_archive_root=prepared_archive_root,
    )
    if result.already_finished:
        logger.info(
            "Canonical full refresh уже завершён для run_id=%s", os.environ["SF_WORKER_RUN_ID"]
        )
        return
    if not result.published:
        stage = {
            "canonical_freshness_failed": "quality",
            "bundle_verification_failed": "predictions",
            "materialization_failed": "publication",
        }.get(result.failure_code, "unknown")
        logger.error(
            "Canonical full refresh не опубликован: run_id=%r stage=%s code=%s",
            os.environ["SF_WORKER_RUN_ID"],
            stage,
            result.failure_code,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
