"""Проверка финальных canonical results для ранее опубликованных прогнозов."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import CanonicalEvent, Prediction
from sports_forecast.validation.gates import ValidationResult


def validate_prediction_result_freshness(
    *,
    session: Session,
    tournament: str,
    refreshed_at: datetime,
    match_duration_minutes: int,
    provider_grace_minutes: int,
) -> ValidationResult:
    """Потребовать `finished` result для прогнозов с истёкшим profile deadline."""
    if match_duration_minutes < 0 or provider_grace_minutes < 0:
        raise ValueError("Параметры deadline не могут быть отрицательными")
    refreshed_utc = (
        refreshed_at.astimezone(UTC) if refreshed_at.tzinfo else refreshed_at.replace(tzinfo=UTC)
    )
    deadline = refreshed_utc - timedelta(minutes=match_duration_minutes + provider_grace_minutes)
    deadline_naive = deadline.replace(tzinfo=None)
    predicted_ids = set(
        session.scalars(
            select(Prediction.match_id).where(
                Prediction.tournament == tournament,
                Prediction.match_datetime.is_not(None),  # type: ignore[attr-defined]
                Prediction.match_datetime <= deadline_naive,
            )
        ).all()
    )
    finished_ids = (
        set(
            session.scalars(
                select(CanonicalEvent.source_event_id).where(
                    CanonicalEvent.tournament == tournament,
                    CanonicalEvent.source_event_id.in_(predicted_ids),  # type: ignore[attr-defined]
                    CanonicalEvent.status == "finished",
                )
            ).all()
        )
        if predicted_ids
        else set()
    )
    missing_count = len(predicted_ids - finished_ids)
    result = ValidationResult(
        is_valid=missing_count == 0,
        stage="canonical_prediction_freshness",
        tournament=tournament,
        n_rows=len(predicted_ids),
        stats={"expired_predictions": len(predicted_ids), "missing_results": missing_count},
    )
    if missing_count:
        result.errors.append(
            f"Отсутствуют финальные результаты ранее спрогнозированных матчей: {missing_count}"
        )
    return result
