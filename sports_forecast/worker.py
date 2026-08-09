"""Одноразовый production Worker для проверенной materialization."""

from __future__ import annotations

import os
from pathlib import Path

import hydra
from omegaconf import DictConfig, open_dict

from sports_forecast.deploy.model_bundle import BundleVerificationError, load_current_model_bundle
from sports_forecast.materialize import materialize_predictions
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.repository import PredictionRepository, WorkerExecutionRepository
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)


def run_worker(
    cfg: DictConfig,
    *,
    run_id: str,
    runtime_root: Path,
    app_version: str,
) -> bool:
    """Проверить immutable input и выполнить один idempotent Worker run."""
    with get_session() as session:
        state = WorkerExecutionRepository(session)
        if not state.start(run_id):
            logger.info("Worker run уже завершён: %s", run_id)
            return True

    try:
        bundle = load_current_model_bundle(runtime_root, app_version=app_version)
    except BundleVerificationError:
        logger.exception("Worker bundle verification завершилась ошибкой")
        with get_session() as session:
            WorkerExecutionRepository(session).fail(
                run_id, failure_code="bundle_verification_failed"
            )
        return False

    with open_dict(cfg):
        cfg.runtime_model_bundle = str(bundle.path)
    success = materialize_predictions(cfg, version="prod")
    with get_session() as session:
        state = WorkerExecutionRepository(session)
        if success:
            predictions_count = PredictionRepository(session).count_showcase(
                tournament=str(cfg.tournament.name),
                market=str(cfg.market.get("name", cfg.market.get("family", "winner"))),
                market_spec=str(cfg.market_spec.name),
            )
            state.succeed(run_id, predictions_count=predictions_count)
        else:
            state.fail(run_id, failure_code="materialization_failed")
    return success


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def main(cfg: DictConfig) -> None:
    """Запустить Worker с обязательными production environment inputs."""
    configure_logging(level=cfg.logging.level)
    run_id = os.environ["SF_WORKER_RUN_ID"]
    runtime_root = Path(os.environ["SF_MODEL_RUNTIME_ROOT"])
    app_version = os.environ["SF_APP_VERSION"]
    if not run_worker(cfg, run_id=run_id, runtime_root=runtime_root, app_version=app_version):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
