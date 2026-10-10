"""Контракт bounded production Worker до materialization."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

from sports_forecast.deploy.model_bundle import (
    BundleVerificationError,
    build_model_bundle,
    install_model_bundle,
)
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


def test_worker_records_failure_when_bundle_file_read_raises_os_error(
    tmp_path: Path, monkeypatch
) -> None:
    """I/O ошибка verifier завершает Worker как failed, не оставляя run started."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"model")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1.0.0",
        source_commit="a" * 40,
        release="v1",
    )
    runtime_root = tmp_path / "runtime"
    install_model_bundle(bundle.path, runtime_root, app_version="1.0.0")
    original_read_bytes = Path.read_bytes

    def fail_model_read(path: Path) -> bytes:
        if path == bundle.path / "model.bin":
            raise OSError("simulated read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_model_read)
    session = MagicMock()
    state = MagicMock()
    state.start.return_value = True
    with (
        patch("sports_forecast.worker.get_session", return_value=nullcontext(session)),
        patch("sports_forecast.worker.WorkerExecutionRepository", return_value=state),
        patch("sports_forecast.worker.materialize_predictions") as materialize,
    ):
        success = run_worker(
            OmegaConf.create({}),
            run_id="io-failure",
            runtime_root=runtime_root,
            app_version="1.0.0",
        )

    assert success is False
    materialize.assert_not_called()
    state.fail.assert_called_once_with("io-failure", failure_code="bundle_verification_failed")


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
        patch(
            "sports_forecast.worker.load_current_model_bundle",
            return_value=MagicMock(path=tmp_path / "verified-bundle"),
        ),
        patch("sports_forecast.worker.materialize_predictions", return_value=True) as materialize,
    ):
        success = run_worker(
            cfg,
            run_id="daily-1",
            runtime_root=tmp_path,
            app_version="1.0.0",
        )

    assert success is True
    state.succeed.assert_called_once_with("daily-1", predictions_count=7)
    passed_cfg = materialize.call_args.args[0]
    assert passed_cfg.runtime_model_bundle == str(tmp_path / "verified-bundle")
    assert passed_cfg.runtime_model_bundle_app_version == "1.0.0"


def test_managed_worker_resolves_database_pointer_without_current_fallback(
    tmp_path: Path,
) -> None:
    """Managed Worker берёт bundle из DB pin и не читает файловый current."""
    session = MagicMock()
    state = MagicMock()
    state.start.return_value = True
    registry = MagicMock()
    registry.get_active.return_value = MagicMock(is_managed=True)
    pin = MagicMock(bundle=MagicMock(path=tmp_path / "sha256:managed"))
    cfg = OmegaConf.create(
        {
            "tournament": {"name": "nhl"},
            "market": {"name": "winner_withOT"},
            "market_spec": {"name": "winner_withOT"},
            "model_pool": {"name": "nhl"},
        }
    )
    with (
        patch("sports_forecast.worker.get_session", return_value=nullcontext(session)),
        patch("sports_forecast.worker.WorkerExecutionRepository", return_value=state),
        patch("sports_forecast.worker.ModelRegistryRepository", return_value=registry),
        patch("sports_forecast.worker.resolve_active_model", return_value=pin),
        patch("sports_forecast.worker.load_current_model_bundle") as load_current,
        patch("sports_forecast.worker.PredictionRepository"),
        patch("sports_forecast.worker.materialize_predictions", return_value=True) as materialize,
    ):
        success = run_worker(
            cfg,
            run_id="managed-run",
            runtime_root=tmp_path,
            app_version="1.2.15",
        )

    assert success is True
    load_current.assert_not_called()
    passed_cfg = materialize.call_args.args[0]
    assert passed_cfg.runtime_model_bundle == str(tmp_path / "sha256:managed")
    assert passed_cfg.runtime_model_bundle_root == str(tmp_path)
