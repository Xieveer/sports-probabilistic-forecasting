"""Атомарная публикация витрины Worker."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import PredictionRepository


def _record(match_id: str) -> dict[str, object]:
    return {
        "match_id": match_id,
        "tournament": "nhl",
        "market": "winner",
        "market_spec": "winner_withOT",
        "predictions": {"home_win": 0.6, "away_win": 0.4},
        "model_version": "immutable",
        "algorithm": "catboost",
        "featureset": "basic",
    }


def test_failed_publication_keeps_last_valid_prediction_showcase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка между stale и upsert не публикует частичную витрину."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            PredictionRepository(session).upsert_prediction(**_record("old"))  # type: ignore[arg-type]

        with pytest.raises(RuntimeError), get_session(engine=engine) as session:
            repository = PredictionRepository(session)
            monkeypatch.setattr(
                repository,
                "upsert_prediction",
                lambda **_: (_ for _ in ()).throw(RuntimeError("write failed")),
            )
            repository.publish_showcase(
                [_record("new")], tournament="nhl", market="winner", market_spec="winner_withOT"
            )

        with get_session(engine=engine) as session:
            rows = session.query(Prediction).all()
            assert [row.match_id for row in rows] == ["old"]
            assert rows[0].status == "ok"
    finally:
        reset_engine()
        engine.dispose()
