"""Контракты immutable model registry и ручного promotion."""

from __future__ import annotations

from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
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
