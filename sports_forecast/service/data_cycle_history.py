"""Безопасные summary и query DTO для истории Data Cycle."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from sports_forecast.service.db.models import DataCycleRun, DataCycleStageResult
from sports_forecast.service.db.repository import (
    DATA_CYCLE_FAILURE_CODES,
    DATA_CYCLE_STAGES,
    DataCycleRunRepository,
)


_COUNT_KEYS = {
    "events",
    "events_found",
    "new_events",
    "changed_events",
    "eligible_events",
    "odds_eligible_events",
    "predictions",
    "predictions_ready",
    "odds_ready",
    "independently_observed_events",
    "fully_ready_events",
    "partially_ready_events",
    "errors",
    "stage_errors",
    "canonical_events",
    "artifacts",
}
_DERIVED_SUMMARY_KEYS = {
    "events_found",
    "new_events",
    "changed_events",
    "eligible_events",
    "odds_eligible_events",
    "predictions_ready",
    "odds_ready",
    "fully_ready_events",
    "partially_ready_events",
    "errors",
    "event_errors",
    "stage_errors",
    "duration_seconds",
    "prediction_coverage",
    "odds_coverage",
}


def _counts(stage: DataCycleStageResult) -> dict[str, int]:
    """Разобрать только известные числовые counters; пропустить неожиданные поля."""
    if not stage.counts_json:
        return {}
    try:
        value = json.loads(stage.counts_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if key in _COUNT_KEYS and isinstance(item, int) and not isinstance(item, bool) and item >= 0
    }


def _find_count(stages: dict[str, dict[str, int]], *keys: str) -> int | None:
    """Найти первый реально записанный stage counter без выдумывания нуля."""
    for values in stages.values():
        for key in keys:
            if key in values:
                return values[key]
    return None


def _coverage(
    numerator: int | None, denominator: int | None
) -> dict[str, int | float | str | None]:
    """Вернуть долю и явную причину unknown/n/a без подмены неизвестного нулём."""
    if denominator == 0:
        status, reason = "n/a", "empty_eligible_set"
    elif numerator is None or denominator is None:
        status, reason = "unknown", "producer_not_recorded"
    else:
        status, reason = "known", None
    ratio = numerator / denominator if numerator is not None and denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio": ratio,
        "status": status,
        "reason_code": reason,
    }


def _readiness_provenance(run: DataCycleRun) -> dict[str, str | None]:
    """Указать persisted as-of публикации, когда producer зафиксировал eligibility."""
    publication = next((stage for stage in run.stages if stage.stage == "publication"), None)
    counts = _counts(publication) if publication is not None else {}
    timestamp = publication.completed_at if publication is not None else None
    if timestamp is not None:
        value = (
            timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        )
        timestamp_text: str | None = value.isoformat().replace("+00:00", "Z")
    else:
        timestamp_text = None
    known = timestamp_text is not None and "eligible_events" in counts
    return {
        "at": timestamp_text,
        "source": "publication_stage.completed_at" if known else None,
        "status": "known" if known else "unknown",
        "reason_code": None if known else "readiness_producer_not_recorded",
    }


def build_run_summary(
    run: DataCycleRun,
    *,
    at: datetime,
    supplemental: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Построить безопасный агрегат из зафиксированных результатов стадий.

    Значения, отсутствующие в stage counters, остаются ``None``. До отдельного
    odds acquisition отсутствие observation не объявляется готовностью.
    """
    stage_counts = {stage.stage: _counts(stage) for stage in run.stages}
    events_found = _find_count(stage_counts, "events_found", "events")
    eligible = _find_count(stage_counts, "eligible_events")
    predictions_ready = _find_count(stage_counts, "predictions_ready")
    odds_ready = _find_count(stage_counts, "odds_ready")
    event_errors = sum(values.get("errors", 0) for values in stage_counts.values())
    stage_errors = sum(
        max(stage_counts[stage.stage].get("stage_errors", 0), int(stage.status == "failed"))
        for stage in run.stages
    )
    errors = event_errors + stage_errors
    odds_denominator = _find_count(stage_counts, "odds_eligible_events")
    duration = (
        max(0.0, (at - run.started_at).total_seconds()) if run.started_at is not None else None
    )
    summary: dict[str, Any] = {
        "events_found": events_found,
        "new_events": _find_count(stage_counts, "new_events"),
        "changed_events": _find_count(stage_counts, "changed_events"),
        "eligible_events": eligible,
        "predictions_ready": predictions_ready,
        "odds_ready": odds_ready,
        "fully_ready_events": _find_count(stage_counts, "fully_ready_events"),
        "partially_ready_events": _find_count(stage_counts, "partially_ready_events"),
        "event_errors": event_errors,
        "stage_errors": stage_errors,
        "errors": errors,
        "duration_seconds": duration,
        "prediction_coverage": _coverage(predictions_ready, eligible),
        "odds_coverage": _coverage(odds_ready, odds_denominator),
        "readiness_as_of": _readiness_provenance(run),
    }
    if supplemental:
        updates = _safe_component_updates(supplemental.get("last_successful_updates"))
        if updates is not None:
            summary["last_successful_updates"] = updates
        for key, value in supplemental.items():
            if (
                key in _COUNT_KEYS
                and key not in _DERIVED_SUMMARY_KEYS
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                summary[key] = value
    return summary


def serialize_run(run: DataCycleRun) -> dict[str, Any]:
    """Сериализовать safe query DTO без сырых деталей, payload или secrets."""
    stage_by_name = {stage.stage: stage for stage in run.stages}
    persisted = _safe_supplemental(run.summary_json) or {}
    persisted.setdefault("last_successful_updates", {})
    summary = build_run_summary(
        run,
        at=run.completed_at or run.heartbeat_at or run.requested_at,
        supplemental=persisted,
    )
    return {
        "run_id": run.run_id,
        "tournament": run.tournament,
        "reason": run.reason if run.reason in {"scheduled", "manual", "retry"} else None,
        "scheduled_for": run.scheduled_for,
        "status": run.status
        if run.status in {"waiting", "running", "success", "partial_success", "failed"}
        else None,
        "current_stage": run.current_stage if run.current_stage in DATA_CYCLE_STAGES else None,
        "failure_code": (
            run.failure_code if run.failure_code in DATA_CYCLE_FAILURE_CODES else None
        ),
        "requested_at": run.requested_at,
        "started_at": run.started_at,
        "heartbeat_at": run.heartbeat_at,
        "completed_at": run.completed_at,
        "summary": summary,
        "stages": [
            {
                "stage": stage.stage,
                "status": stage.status
                if stage.status
                in {"waiting", "running", "success", "partial_success", "failed", "skipped"}
                else None,
                "failure_code": (
                    stage.failure_code if stage.failure_code in DATA_CYCLE_FAILURE_CODES else None
                ),
                "started_at": stage.started_at,
                "completed_at": stage.completed_at,
                "counts": _counts(stage),
            }
            for stage_name in DATA_CYCLE_STAGES
            if (stage := stage_by_name.get(stage_name)) is not None
        ],
    }


def _safe_component_updates(value: object) -> dict[str, dict[str, str | None]] | None:
    """Вернуть только allowlisted component timestamps с известным provenance."""
    if not isinstance(value, dict):
        return None
    expected = {
        "calendar": "calendar_coverages.last_successful_at",
        "odds": "odds_observations.retrieved_at",
        "predictions": "predictions.prediction_ts",
    }
    result: dict[str, dict[str, str | None]] = {}
    for component, source_stage in expected.items():
        item = value.get(component)
        timestamp = item.get("last_successful_at") if isinstance(item, dict) else None
        if not isinstance(timestamp, str):
            timestamp = None
        else:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    timestamp = None
                else:
                    timestamp = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except ValueError:
                timestamp = None
        result[component] = {
            "last_successful_at": timestamp,
            "source": source_stage,
            "status": "known" if timestamp is not None else "unknown",
        }
    return result


def _safe_supplemental(raw: str | None) -> dict[str, Any] | None:
    """Вернуть из persisted summary только known counters и component provenance."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {
        key: count
        for key, count in value.items()
        if key in _COUNT_KEYS
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
    }
    updates = _safe_component_updates(value.get("last_successful_updates"))
    if updates is not None:
        result["last_successful_updates"] = updates
    return result


def get_current_run(session: Session, tournament: str) -> dict[str, Any] | None:
    """Вернуть safe DTO текущего run для выбранного tournament/pipeline."""
    run = DataCycleRunRepository(session).get_current(tournament)
    return serialize_run(run) if run is not None else None


def list_recent_runs(
    session: Session,
    tournament: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Вернуть ограниченную safe DTO историю без league-specific полей."""
    runs = DataCycleRunRepository(session).list_recent(tournament, limit=limit)
    return [serialize_run(run) for run in runs]
