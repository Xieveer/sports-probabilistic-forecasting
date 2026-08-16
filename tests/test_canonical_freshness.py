"""Freshness gate для ранее опубликованных prediction в canonical store."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import Base, CanonicalEvent, Prediction
from sports_forecast.validation.canonical_freshness import validate_prediction_result_freshness


def test_missing_finished_result_after_profile_deadline_blocks_tournament() -> None:
    """Прогноз с истёкшим deadline требует canonical finished result."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        session.add(
            Prediction(
                match_id="100",
                tournament="nhl",
                market="winner",
                market_spec="winner_withOT",
                model_version="test",
                algorithm="catboost",
                featureset="advanced",
                predictions_json="{}",
                match_datetime=datetime(2026, 8, 14, 10, 0),
            )
        )
        session.add(
            CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="100",
                scheduled_at=datetime(2026, 8, 14, 10, 0),
                status="upcoming",
                current_revision_sha256="a" * 64,
            )
        )
        session.commit()

        result = validate_prediction_result_freshness(
            session=session,
            tournament="nhl",
            refreshed_at=datetime(2026, 8, 14, 14, 0, tzinfo=UTC),
            match_duration_minutes=210,
            provider_grace_minutes=30,
        )

        assert result.is_valid is False
        assert result.errors == [
            "Отсутствуют финальные результаты ранее спрогнозированных матчей: 1"
        ]
    finally:
        session.close()
