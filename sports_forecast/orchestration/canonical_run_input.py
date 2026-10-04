"""Закреплённый NHL snapshot между сбором, Object Storage и расчётом."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from sports_forecast.config.loaders import load_tournament_quality_gate_config
from sports_forecast.deploy.canonical_bootstrap import refresh_nhl_canonical_with_summary_from_csv
from sports_forecast.deploy.canonical_snapshot import export_canonical_snapshot
from sports_forecast.deploy.serving_data import verify_archive
from sports_forecast.deploy.source_state import (
    export_nhl_source_state,
    verify_nhl_source_state_bundle,
)
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.repository import DataCycleRunRepository
from sports_forecast.validation.canonical_freshness import validate_prediction_result_freshness


_RUN_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_ARTIFACT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class PreparedRunInput:
    """Проверенный модельный вход и ID точно синхронизированного архива."""

    rows: list[dict[str, Any]]
    canonical_artifact_id: str


def run_input_path(archive_root: Path, run_id: str) -> Path:
    """Вернуть безопасный путь descriptor одного Data Cycle run."""
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("Некорректный run_id для snapshot")
    return archive_root / "run-inputs" / f"{run_id}.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail_current_stage(run_id: str) -> None:
    """Сохранить ошибку активной стадии без provider payload в истории."""
    with get_session() as session:
        cycle = DataCycleRunRepository(session)
        run = cycle.get(run_id)
        if run is not None and run.status in {"waiting", "running"}:
            cycle.fail_run(run_id, failure_code="executor_interrupted")


def prepare_run_input(
    *,
    run_id: str,
    source_csv: Path,
    archive_root: Path,
    refreshed_at: datetime,
    config_id: str,
) -> Path:
    """Импортировать source, проверить качество и архивировать вход до features.

    После возврата стадия ``archive_sync`` остаётся running: host обязан
    подтвердить Object Storage до запуска Worker.
    """
    descriptor = run_input_path(archive_root, run_id)
    try:
        source_hash = _sha256(source_csv)
        with get_session() as session:
            summary = refresh_nhl_canonical_with_summary_from_csv(source_csv, session)
        with get_session() as session:
            cycle = DataCycleRunRepository(session)
            cycle.finish_stage(
                run_id,
                "calendar",
                status="success",
                counts={
                    "events": summary.events_found,
                    "events_found": summary.events_found,
                    "new_events": summary.new_events,
                    "changed_events": summary.changed_events,
                },
            )
            cycle.start_stage(run_id, "quality")
        quality = load_tournament_quality_gate_config("nhl")
        with get_session() as session:
            freshness = validate_prediction_result_freshness(
                session=session,
                tournament="nhl",
                refreshed_at=refreshed_at,
                match_duration_minutes=quality.match_duration_minutes,
                provider_grace_minutes=quality.provider_grace_minutes,
            )
        if not freshness.is_valid:
            raise ValueError("Canonical freshness quality gate отклонил snapshot")
        with get_session() as session:
            cycle = DataCycleRunRepository(session)
            cycle.finish_stage(run_id, "quality", status="success")
            cycle.start_stage(run_id, "archive_sync")
        with get_session() as session:
            canonical = export_canonical_snapshot(
                session,
                tournament="nhl",
                archive_root=archive_root,
                run_id=run_id,
                config_id=config_id,
                source="nhl_web_api",
            )
        source = export_nhl_source_state(source_csv, archive_root, run_id=run_id)
        if _sha256(source.path / "source.csv") != source_hash or _sha256(source_csv) != source_hash:
            raise ValueError("Source изменился во время подготовки snapshot")
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "canonical_artifact_id": canonical.artifact_id,
            "source_artifact_id": source.artifact_id,
        }
        descriptor.parent.mkdir(parents=True, exist_ok=True)
        temporary = descriptor.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(descriptor)
        return descriptor
    except Exception:
        _fail_current_stage(run_id)
        raise


def load_prepared_input(*, run_id: str, archive_root: Path) -> PreparedRunInput:
    """Прочитать только проверенный immutable canonical archive этого run."""
    descriptor = run_input_path(archive_root, run_id)
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Descriptor подготовленного snapshot недоступен") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise ValueError("Descriptor не соответствует Data Cycle run")
    canonical_id = payload.get("canonical_artifact_id")
    source_id = payload.get("source_artifact_id")
    if not isinstance(canonical_id, str) or not _ARTIFACT_ID.fullmatch(canonical_id):
        raise ValueError("Некорректный canonical artifact ID")
    if not isinstance(source_id, str) or not _ARTIFACT_ID.fullmatch(source_id):
        raise ValueError("Некорректный source artifact ID")
    canonical_path = archive_root / "operational-archive" / canonical_id
    source_path = archive_root / "operational-archive/nhl-source-state/v1" / source_id
    verify_archive(canonical_path)
    verify_nhl_source_state_bundle(source_path)
    manifest = json.loads((canonical_path / "manifest.json").read_text(encoding="utf-8"))
    source_manifest = json.loads((source_path / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("provenance", {}).get("run_id") != run_id
        or source_manifest.get("provenance", {}).get("run_id") != run_id
    ):
        raise ValueError("Архивы не принадлежат текущему run")
    with get_session() as session:
        cycle = DataCycleRunRepository(session).get(run_id)
        if cycle is None or not all(
            any(stage.stage == name and stage.status == "success" for stage in cycle.stages)
            for name in ("calendar", "quality", "archive_sync")
        ):
            raise ValueError("Object Storage sync ещё не подтверждён")
    frame = pd.read_parquet(
        canonical_path / "partitions" / "tournament=nhl" / "canonical_events.parquet"
    )
    rows: list[dict[str, Any]] = []
    for item in frame.sort_values("source_event_id").to_dict("records"):
        try:
            source_payload = json.loads(item["payload_json"])
            result_payload = json.loads(item["result_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Canonical archive содержит невалидный JSON") from exc
        if not isinstance(source_payload, dict) or not isinstance(result_payload, dict):
            raise ValueError("Canonical archive не соответствует payload contract")
        row = dict(source_payload)
        row.update({key: value for key, value in result_payload.items() if value is not None})
        row["id"] = str(item["source_event_id"])
        scheduled = item["scheduled_at"]
        row["datetime"] = scheduled.isoformat()
        row["match_is_end"] = "1" if item["status"] == "finished" else "0"
        rows.append(row)
    if not rows:
        raise ValueError("Canonical archive не содержит событий")
    return PreparedRunInput(rows=rows, canonical_artifact_id=canonical_id)
