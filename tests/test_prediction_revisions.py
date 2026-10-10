"""Контракт неизменяемых версий опубликованных прогнозов."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import StaticPool

from sports_forecast.service.app import app
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import Prediction, PredictionRevision
from sports_forecast.service.db.repository import PredictionRepository


def _record(*, run_id: str = "run-1", tournament: str = "nhl", p: float = 0.6) -> dict[str, object]:
    return {
        "match_id": "game-1",
        "tournament": tournament,
        "market": "winner",
        "market_spec": "winner_withOT",
        "predictions": {"home_win": p, "away_win": 1 - p},
        "model_version": "catboost_prod",
        "algorithm": "catboost",
        "featureset": "basic",
        "model_pool": "nhl",
        "immutable_model_version": "model-v1",
        "bundle_id": "bundle-v1",
        "model_identity": "identity-v1",
        "feature_contract_id": "features-v1",
        "refresh_run_id": run_id,
        "source_namespace": "nhl_api",
        "input_snapshot_ref": "snapshot-v1",
    }


@pytest.fixture
def db_engine():
    reset_engine()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    yield engine
    reset_engine()
    engine.dispose()


def _publish(session, record: dict[str, object]) -> None:
    PredictionRepository(session).publish_showcase(
        [record], tournament=str(record["tournament"]), market="winner", market_spec="winner_withOT"
    )


def test_managed_publication_is_idempotent_and_rejects_changed_payload(db_engine) -> None:
    with get_session(engine=db_engine) as session:
        _publish(session, _record())
    with get_session(engine=db_engine) as session:
        _publish(session, _record())
    with get_session(engine=db_engine) as session:
        revisions = session.query(PredictionRevision).all()
        current = session.query(Prediction).one()
        assert len(revisions) == 1
        assert current.current_revision_id == revisions[0].revision_id
        old_revision = PredictionRepository(session).get_revision(revisions[0].revision_id)
        assert json.loads(old_revision.probabilities_json) == {"home_win": 0.6, "away_win": 0.4}

    with pytest.raises(ValueError, match="payload"), get_session(engine=db_engine) as session:
        _publish(session, _record(p=0.7))


def test_new_run_and_tournament_are_distinct_showcase_keys(db_engine) -> None:
    with get_session(engine=db_engine) as session:
        _publish(session, _record())
        old_id = session.query(PredictionRevision).one().revision_id
    with get_session(engine=db_engine) as session:
        _publish(session, _record(run_id="run-2"))
        _publish(session, _record(run_id="run-1", tournament="nhl_preseason"))
    with get_session(engine=db_engine) as session:
        rows = session.query(Prediction).order_by(Prediction.tournament).all()
        revisions = session.query(PredictionRevision).all()
        assert len(rows) == 2
        assert len(revisions) == 3
        assert {row.tournament for row in rows} == {"nhl", "nhl_preseason"}
        assert PredictionRepository(session).get_revision(old_id).probabilities_json == (
            '{"away_win": 0.4, "home_win": 0.6}'
        )


def test_revision_creation_rolls_back_with_failed_showcase(db_engine, monkeypatch) -> None:
    with pytest.raises(RuntimeError), get_session(engine=db_engine) as session:
        repo = PredictionRepository(session)
        monkeypatch.setattr(
            repo, "upsert_prediction", lambda **_: (_ for _ in ()).throw(RuntimeError())
        )
        repo.publish_showcase(
            [_record()], tournament="nhl", market="winner", market_spec="winner_withOT"
        )
    with get_session(engine=db_engine) as session:
        assert session.query(PredictionRevision).count() == 0
        assert session.query(Prediction).count() == 0


def test_empty_showcase_keeps_immutable_history(db_engine) -> None:
    with get_session(engine=db_engine) as session:
        _publish(session, _record())
    with get_session(engine=db_engine) as session:
        repo = PredictionRepository(session)
        repo.publish_showcase([], tournament="nhl", market="winner", market_spec="winner_withOT")
    with get_session(engine=db_engine) as session:
        current = session.query(Prediction).one()
        assert current.status == "stale"
        assert current.current_revision_id is not None
        assert session.query(PredictionRevision).count() == 1


def test_legacy_prediction_keeps_nullable_revision_reference(db_engine) -> None:
    with get_session(engine=db_engine) as session:
        PredictionRepository(session).upsert_prediction(
            match_id="legacy",
            tournament="nhl",
            market="winner",
            market_spec="winner_withOT",
            predictions={"home_win": 0.5, "away_win": 0.5},
            model_version="legacy",
            algorithm="catboost",
            featureset="basic",
        )
    with get_session(engine=db_engine) as session:
        assert session.query(Prediction).one().current_revision_id is None
        assert session.query(PredictionRevision).count() == 0


def test_prediction_api_continues_to_return_current_showcase(db_engine, monkeypatch) -> None:
    from sports_forecast.service.routers import predictions as prediction_router

    def test_session():
        return get_session(engine=db_engine)

    monkeypatch.setattr(prediction_router, "get_session", test_session)
    monkeypatch.setattr(prediction_router, "batch_live_response_extras", lambda *_a, **_k: {})
    future = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None)
    api_record = _record(run_id="run-api")
    api_record["match_datetime"] = future
    api_record["home_player"] = "CAR"
    api_record["away_player"] = "BUF"
    with get_session(engine=db_engine) as session:
        _publish(session, api_record)
    second_api_record = dict(api_record)
    second_api_record.update(
        {"refresh_run_id": "run-api-2", "predictions": {"home_win": 0.7, "away_win": 0.3}}
    )
    with get_session(engine=db_engine) as session:
        _publish(session, second_api_record)
    response = TestClient(app).get(
        "/predict/upcoming/nhl",
        params={"market": "winner", "market_spec": "winner_withOT", "live_pinnacle": "false"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["predictions"][0]["predictions"] == {"home_win": 0.7, "away_win": 0.3}


@pytest.mark.integration
def test_postgres_revision_and_showcase_rollback_together() -> None:
    """PostgreSQL откатывает revision и showcase одной транзакцией."""
    database_url = os.environ.get("SF_TEST_PREDICTION_REVISION_DATABASE_URL")
    if not database_url:
        pytest.skip("Нужен disposable PostgreSQL с применённой Alembic head revision")
    engine = create_engine(database_url, pool_size=2)
    event_id = f"revision-test-{uuid4().hex}"
    record = _record(run_id=event_id)
    record["match_id"] = event_id
    try:
        with (
            pytest.raises(RuntimeError, match="rollback after revision"),
            get_session(engine=engine) as session,
        ):
            repository = PredictionRepository(session)
            repository.publish_showcase(
                [record], tournament="nhl", market="winner", market_spec="winner_withOT"
            )
            raise RuntimeError("rollback after revision")
        with get_session(engine=engine) as session:
            assert (
                session.scalar(
                    select(PredictionRevision.revision_id).where(
                        PredictionRevision.run_id == event_id
                    )
                )
                is None
            )
            assert session.query(Prediction).filter_by(match_id=event_id).count() == 0
        with get_session(engine=engine) as session:
            PredictionRepository(session).publish_showcase(
                [record], tournament="nhl", market="winner", market_spec="winner_withOT"
            )
        with pytest.raises(DBAPIError), get_session(engine=engine) as session:
            session.execute(
                update(PredictionRevision)
                .where(PredictionRevision.run_id == event_id)
                .values(probabilities_json="{}")
            )
    finally:
        engine.dispose()
