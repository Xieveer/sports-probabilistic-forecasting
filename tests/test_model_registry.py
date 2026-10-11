"""Контракты immutable model registry и ручного promotion."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import ModelDeployment
from sports_forecast.service.db.repository import ModelRegistryRepository


def test_explicit_promotion_updates_pointer_and_preserves_previous_version() -> None:
    """Только явный promotion меняет active pointer, сохраняя прежнюю версию."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            registry = ModelRegistryRepository(session)
            first = registry.promote(
                model_pool="football_nationals_winner",
                market_spec="winner",
                model_identity="pool:football_nationals_winner:winner:first",
                candidate_report_ref="reports/first.json",
                artifact_ref="models/pools/football_nationals_winner/winner/first",
            )
            second = registry.promote(
                model_pool="football_nationals_winner",
                market_spec="winner",
                model_identity="pool:football_nationals_winner:winner:second",
                candidate_report_ref="reports/second.json",
                artifact_ref="models/pools/football_nationals_winner/winner/second",
            )

            active = registry.get_active("football_nationals_winner", "winner")

            assert active is not None
            assert active.model_identity == second.model_identity
            assert registry.get_by_identity(first.model_identity).is_active is False
    finally:
        engine.dispose()
        reset_engine()


def test_rollback_reactivates_previous_pointer_without_deleting_version() -> None:
    """Rollback возвращает выбранную immutable версию, не удаляя newer record."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            registry = ModelRegistryRepository(session)
            first = registry.promote(
                model_pool="football_nationals_winner",
                market_spec="winner",
                model_identity="pool:football_nationals_winner:winner:first",
                candidate_report_ref="reports/first.json",
                artifact_ref="models/pools/football_nationals_winner/winner/first",
            )
            second = registry.promote(
                model_pool="football_nationals_winner",
                market_spec="winner",
                model_identity="pool:football_nationals_winner:winner:second",
                candidate_report_ref="reports/second.json",
                artifact_ref="models/pools/football_nationals_winner/winner/second",
            )

            rolled_back = registry.rollback(
                "football_nationals_winner", "winner", first.model_identity
            )

            assert rolled_back.model_identity == first.model_identity
            assert registry.get_by_identity(second.model_identity).is_active is False
    finally:
        engine.dispose()
        reset_engine()


def test_managed_deployment_requires_bundle_and_has_one_active_per_pair() -> None:
    """DB constraint допускает только один active managed deployment с bundle."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            registry = ModelRegistryRepository(session)
            registry.promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:first",
                candidate_report_ref="reports/first.json",
                artifact_ref="bundles/sha256:first",
                bundle_id="sha256:first",
                managed_artifact_location="bundles/sha256:first/model.cbm",
            )
            registry.promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:second",
                candidate_report_ref="reports/second.json",
                artifact_ref="bundles/sha256:second",
                bundle_id="sha256:second",
                managed_artifact_location="bundles/sha256:second/model.cbm",
            )
            active = registry.get_active("nhl", "winner_withOT")
            assert active is not None
            assert active.bundle_id == "sha256:second"
            assert registry.get_by_identity("pool:nhl:winner_withOT:first").is_active is False
            unbound = ModelDeployment(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:unbound",
                candidate_report_ref="reports/unbound.json",
                artifact_ref="legacy/path",
                is_managed=True,
                is_active=False,
            )
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(unbound)
                session.flush()
            duplicate_active = ModelDeployment(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity="pool:nhl:winner_withOT:duplicate",
                candidate_report_ref="reports/duplicate.json",
                artifact_ref="legacy/duplicate",
                is_managed=False,
                is_active=True,
            )
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(duplicate_active)
                session.flush()
    finally:
        engine.dispose()
        reset_engine()


def test_legacy_identity_requires_explicit_one_time_bundle_bind() -> None:
    """Существующий legacy identity можно связать с bundle ровно один раз."""
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
            bound = registry.promote_managed(
                model_pool="nhl",
                market_spec="winner_withOT",
                model_identity=legacy.model_identity,
                candidate_report_ref="reports/approved.json",
                artifact_ref="sha256:bound",
                bundle_id="sha256:bound",
                managed_artifact_location="sha256:bound/model.bin",
            )
            assert bound.id == legacy.id
            assert bound.is_managed is True
            assert bound.bundle_id == "sha256:bound"
            with pytest.raises(ValueError, match="уже привязан"):
                registry.promote_managed(
                    model_pool="nhl",
                    market_spec="winner_withOT",
                    model_identity=legacy.model_identity,
                    candidate_report_ref="reports/rebind.json",
                    artifact_ref="sha256:other",
                    bundle_id="sha256:other",
                    managed_artifact_location="sha256:other/model.bin",
                )
    finally:
        engine.dispose()
        reset_engine()
