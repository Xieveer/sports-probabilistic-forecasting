"""Контракт bounded production Worker до materialization."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

from sports_forecast.deploy.model_bundle import BundleVerificationError
from sports_forecast.worker import run_worker


def test_worker_verifies_bundle_before_materialization(tmp_path: Path) -> None:
    """Повреждённый bundle не допускает inference или запись predictions."""
    session = MagicMock()
    state = MagicMock()
    state.start.return_value = True
    with (
        patch("sports_forecast.worker.get_session", return_value=nullcontext(session)),
        patch("sports_forecast.worker.WorkerExecutionRepository", return_value=state),
        patch(
            "sports_forecast.worker.load_current_model_bundle",
            side_effect=BundleVerificationError("bad"),
        ),
        patch("sports_forecast.worker.materialize_predictions") as materialize,
    ):
        success = run_worker(
            OmegaConf.create({}),
            run_id="daily-1",
            runtime_root=tmp_path,
            app_version="1.0.0",
        )

    assert success is False
    materialize.assert_not_called()
    state.fail.assert_called_once_with("daily-1", failure_code="bundle_verification_failed")


def test_completed_run_is_not_materialized_twice(tmp_path: Path) -> None:
    """Повтор одного scheduler run не меняет витрину повторно."""
    session = MagicMock()
    state = MagicMock()
    state.start.return_value = False
    with (
        patch("sports_forecast.worker.get_session", return_value=nullcontext(session)),
        patch("sports_forecast.worker.WorkerExecutionRepository", return_value=state),
        patch("sports_forecast.worker.materialize_predictions") as materialize,
    ):
        success = run_worker(
            OmegaConf.create({}),
            run_id="daily-1",
            runtime_root=tmp_path,
            app_version="1.0.0",
        )

    assert success is True
    materialize.assert_not_called()


def test_successful_worker_stores_published_predictions_count(tmp_path: Path) -> None:
    """Last-success содержит счётчик, а не фиктивное значение."""
    session = MagicMock()
    state = MagicMock()
    state.start.return_value = True
    predictions = MagicMock()
    predictions.count_showcase.return_value = 7
    cfg = OmegaConf.create(
        {
            "tournament": {"name": "nhl"},
            "market": {"name": "winner_withOT"},
            "market_spec": {"name": "winner_withOT"},
        }
    )
    with (
        patch("sports_forecast.worker.get_session", return_value=nullcontext(session)),
        patch("sports_forecast.worker.WorkerExecutionRepository", return_value=state),
        patch("sports_forecast.worker.PredictionRepository", return_value=predictions),
        patch("sports_forecast.worker.load_current_model_bundle"),
        patch("sports_forecast.worker.materialize_predictions", return_value=True),
    ):
        success = run_worker(
            cfg,
            run_id="daily-1",
            runtime_root=tmp_path,
            app_version="1.0.0",
        )

    assert success is True
    state.succeed.assert_called_once_with("daily-1", predictions_count=7)
