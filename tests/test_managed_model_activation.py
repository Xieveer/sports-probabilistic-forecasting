"""Проверки managed pointer activation и pinned bundle resolution."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, delete

from sports_forecast.deploy.managed_model import (
    PinnedModelContract,
    activate_managed_model,
    deployment_matches_pin,
    resolve_active_model,
    rollback_managed_model,
)
from sports_forecast.deploy.model_bundle import build_managed_model_bundle
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import ModelDeployment
from sports_forecast.service.db.repository import ModelRegistryRepository


def _build_managed_bundle(root: Path, *, identity: str = "pool:nhl:winner_withOT:first"):
    source = root / "source"
    source.mkdir(parents=True)
    (source / "model.bin").write_bytes(b"trusted model")
    return build_managed_model_bundle(
        source,
        root / "bundles",
        model_identity=identity,
        app_version="1.2.15",
        model_pool="nhl",
        market_spec="winner_withOT",
        market_rules={"overtime": True, "shootout": True, "draw": False},
        outcomes=["home_win", "away_win"],
        feature_contract_id="features-v1",
        features=[{"name": "f1", "type": "float"}],
        transformations_version="v1",
        algorithm="lgbm",
        model_entrypoint="model.bin",
    )


def test_activation_binds_verified_bundle_and_resolver_returns_exact_entrypoint(
    tmp_path: Path,
) -> None:
    """DB pointer и resolver используют одну v2 bundle identity и entrypoint."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    bundle = _build_managed_bundle(tmp_path)
    loader = Mock(return_value=object())
    try:
        with get_session(engine=engine) as session:
            deployment = activate_managed_model(
                session,
                bundle_path=bundle.path,
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
                model_pool="nhl",
                market_spec="winner_withOT",
                candidate_report_ref="reports/approved.json",
                feature_contract_id="features-v1",
                features=[{"name": "f1", "type": "float"}],
                load_model=loader,
            )
        assert deployment.bundle_id == bundle.bundle_id
        assert deployment.is_managed is True
        loader.assert_called_once_with(bundle.path / "model.bin", "lgbm")
        with get_session(engine=engine) as session:
            pin = resolve_active_model(
                session,
                model_pool="nhl",
                market_spec="winner_withOT",
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
            )
        assert pin.bundle_id == bundle.bundle_id
        assert pin.model_file == bundle.path / "model.bin"
    finally:
        engine.dispose()
        reset_engine()


def test_activation_does_not_change_pointer_when_loader_rejects_candidate(
    tmp_path: Path,
) -> None:
    """Ошибка реальной загрузки не меняет ранее active deployment."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    first = _build_managed_bundle(tmp_path, identity="pool:nhl:winner_withOT:first")
    second_source = tmp_path / "source-second"
    second_source.mkdir()
    (second_source / "model.bin").write_bytes(b"second model")
    second = build_managed_model_bundle(
        second_source,
        tmp_path / "bundles",
        model_identity="pool:nhl:winner_withOT:second",
        app_version="1.2.15",
        model_pool="nhl",
        market_spec="winner_withOT",
        market_rules={"overtime": True, "shootout": True, "draw": False},
        outcomes=["home_win", "away_win"],
        feature_contract_id="features-v1",
        features=[{"name": "f1", "type": "float"}],
        transformations_version="v1",
        algorithm="lgbm",
        model_entrypoint="model.bin",
    )
    try:
        with get_session(engine=engine) as session:
            activate_managed_model(
                session,
                bundle_path=first.path,
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
                model_pool="nhl",
                market_spec="winner_withOT",
                candidate_report_ref="reports/first.json",
                feature_contract_id="features-v1",
                features=[{"name": "f1", "type": "float"}],
                load_model=lambda *_: object(),
            )
        with (
            pytest.raises(RuntimeError, match="load failed"),
            get_session(engine=engine) as session,
        ):
            activate_managed_model(
                session,
                bundle_path=second.path,
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
                model_pool="nhl",
                market_spec="winner_withOT",
                candidate_report_ref="reports/second.json",
                feature_contract_id="features-v1",
                features=[{"name": "f1", "type": "float"}],
                load_model=lambda *_: (_ for _ in ()).throw(RuntimeError("load failed")),
            )
        with get_session(engine=engine) as session:
            pin = resolve_active_model(
                session,
                model_pool="nhl",
                market_spec="winner_withOT",
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
            )
        assert pin.bundle_id == first.bundle_id
    finally:
        engine.dispose()
        reset_engine()


def test_managed_rollback_verifies_and_restores_registered_bundle(tmp_path: Path) -> None:
    """Managed rollback reloads a verified bundle before restoring its pointer."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    first = _build_managed_bundle(tmp_path, identity="pool:nhl:winner_withOT:first")
    second_source = tmp_path / "second-source"
    second_source.mkdir()
    (second_source / "model.bin").write_bytes(b"second")
    second = build_managed_model_bundle(
        second_source,
        tmp_path / "bundles",
        model_identity="pool:nhl:winner_withOT:second",
        app_version="1.2.15",
        model_pool="nhl",
        market_spec="winner_withOT",
        market_rules={"overtime": True, "shootout": True, "draw": False},
        outcomes=["home_win", "away_win"],
        feature_contract_id="features-v1",
        features=[{"name": "f1", "type": "float"}],
        transformations_version="v1",
        algorithm="lgbm",
        model_entrypoint="model.bin",
    )
    try:
        with get_session(engine=engine) as session:
            for bundle, report in ((first, "first"), (second, "second")):
                activate_managed_model(
                    session,
                    bundle_path=bundle.path,
                    bundle_root=tmp_path / "bundles",
                    app_version="1.2.15",
                    model_pool="nhl",
                    market_spec="winner_withOT",
                    candidate_report_ref=f"reports/{report}.json",
                    feature_contract_id="features-v1",
                    features=[{"name": "f1", "type": "float"}],
                    load_model=lambda *_: object(),
                )
        with get_session(engine=engine) as session:
            restored = rollback_managed_model(
                session,
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity=first.model_identity,
                bundle_root=tmp_path / "bundles",
                app_version="1.2.15",
                load_model=lambda *_: object(),
            )
            assert restored.bundle_id == first.bundle_id
        with get_session(engine=engine) as session:
            active = ModelRegistryRepository(session).get_active("nhl", "winner_withOT")
            assert active is not None and active.model_identity == first.model_identity
    finally:
        engine.dispose()
        reset_engine()


def test_legacy_promote_cannot_replace_active_managed_pointer(tmp_path: Path) -> None:
    """Legacy promotion is rejected while its pair has a managed pointer."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            registry = ModelRegistryRepository(session)
            legacy = registry.promote(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:legacy",
                candidate_report_ref="reports/legacy.json",
                artifact_ref="models/legacy",
            )
            current = registry.promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:managed",
                candidate_report_ref="reports/managed.json",
                artifact_ref="sha256:managed",
                bundle_id="sha256:managed",
                managed_artifact_location="sha256:managed/model.bin",
            )
            with pytest.raises(ValueError, match="managed"):
                registry.promote(
                    model_pool="nhl",
                    market_spec="winner_withOT",
                    model_identity="pool:nhl:winner_withOT:legacy",
                    candidate_report_ref="reports/legacy.json",
                    artifact_ref="models/legacy",
                )
            with pytest.raises(ValueError, match="managed rollback"):
                registry.rollback("nhl", "winner_withOT", current.model_identity)
            with pytest.raises(ValueError, match="active managed"):
                registry.rollback("nhl", "winner_withOT", legacy.model_identity)
            assert registry.get_active("nhl", "winner_withOT").id == current.id
    finally:
        engine.dispose()
        reset_engine()


@pytest.mark.integration
def test_postgres_promotion_between_pin_and_publish_rejects_old_bundle() -> None:
    """PostgreSQL concurrency race rejects stale inference before publication."""
    database_url = os.environ.get("SF_TEST_MANAGED_MODEL_DATABASE_URL")
    if not database_url:
        pytest.skip("Нужен disposable PostgreSQL в SF_TEST_MANAGED_MODEL_DATABASE_URL")
    engine = create_engine(database_url, pool_size=4)
    ModelDeployment.__table__.create(engine, checkfirst=True)
    pinned_event = threading.Event()
    promoted_event = threading.Event()
    result: dict[str, bool] = {}

    def inference_worker() -> None:
        with get_session(engine=engine) as session:
            old = ModelRegistryRepository(session).get_active("nhl", "winner_withOT")
            assert old is not None
            pin = PinnedModelContract(
                deployment_id=old.id,
                model_identity=old.model_identity,
                bundle_id=old.bundle_id,
                bundle=Mock(),
                model_file=Path("unused"),
            )
            pinned_event.set()
            assert promoted_event.wait(timeout=5)
            result["current"] = deployment_matches_pin(session, "nhl", "winner_withOT", pin)

    try:
        with engine.begin() as connection:
            connection.execute(
                delete(ModelDeployment).where(
                    ModelDeployment.model_pool == "nhl",
                    ModelDeployment.market_spec == "winner_withOT",
                )
            )
        with get_session(engine=engine) as session:
            ModelRegistryRepository(session).promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:postgres-old",
                candidate_report_ref="reports/old.json",
                artifact_ref="sha256:postgres-old",
                bundle_id="sha256:postgres-old",
                managed_artifact_location="sha256:postgres-old/model.bin",
            )
        thread = threading.Thread(target=inference_worker)
        thread.start()
        assert pinned_event.wait(timeout=5)
        with get_session(engine=engine) as session:
            ModelRegistryRepository(session).promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:postgres-new",
                candidate_report_ref="reports/new.json",
                artifact_ref="sha256:postgres-new",
                bundle_id="sha256:postgres-new",
                managed_artifact_location="sha256:postgres-new/model.bin",
            )
        promoted_event.set()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert result["current"] is False
    finally:
        promoted_event.set()
        with engine.begin() as connection:
            connection.execute(
                delete(ModelDeployment).where(
                    ModelDeployment.model_pool == "nhl",
                    ModelDeployment.market_spec == "winner_withOT",
                )
            )
        engine.dispose()
