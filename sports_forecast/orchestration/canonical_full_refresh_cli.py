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
    source_csv = Path(os.environ["SF_CANONICAL_SOURCE_CSV"])
    result = run_full_refresh(
        cfg,
        run_id=os.environ["SF_WORKER_RUN_ID"],
        runtime_root=Path(os.environ["SF_MODEL_RUNTIME_ROOT"]),
        app_version=os.environ["SF_APP_VERSION"],
        refreshed_at=datetime.now(UTC),
        source_csv=source_csv,
        archive_root=Path(os.environ["SF_OPERATIONAL_ARCHIVE_ROOT"]),
    )
    if not result.published:
        logger.error("Canonical full refresh не опубликован: %s", result.failure_code)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
