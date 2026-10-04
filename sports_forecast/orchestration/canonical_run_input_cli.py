"""Подготовка canonical и immutable input до Object Storage sync."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import hydra
from omegaconf import DictConfig, OmegaConf

from sports_forecast.orchestration.canonical_run_input import prepare_run_input
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)


@hydra.main(config_path="../../conf", config_name="config", version_base="1.3")
def main(cfg: DictConfig) -> None:
    """Подготовить проверенные архивы одного scheduler run без odds и features."""
    configure_logging(level=cfg.logging.level)
    run_id = os.environ["SF_WORKER_RUN_ID"]
    descriptor = prepare_run_input(
        run_id=run_id,
        source_csv=Path(os.environ["SF_CANONICAL_SOURCE_CSV"]),
        archive_root=Path(os.environ["SF_OPERATIONAL_ARCHIVE_ROOT"]),
        refreshed_at=datetime.now(UTC),
        config_id="sha256:"
        + hashlib.sha256(OmegaConf.to_yaml(cfg, resolve=True).encode("utf-8")).hexdigest(),
    )
    logger.info("Canonical input подготовлен для run_id=%s: %s", run_id, descriptor)


if __name__ == "__main__":
    main()
