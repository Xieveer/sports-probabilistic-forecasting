"""Экспорт current canonical revisions в immutable operational archive."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.deploy.serving_data import ArchiveArtifact, archive_snapshot
from sports_forecast.service.db.models import CanonicalEvent, CanonicalEventRevision


def _snapshot_id(rows: list[dict[str, Any]]) -> str:
    """Вернуть stable identity canonical rows без записи provider payload в лог."""
    encoded = json.dumps(rows, sort_keys=True, default=str, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def export_canonical_snapshot(
    session: Session,
    *,
    tournament: str,
    archive_root: Path,
    run_id: str,
    config_id: str,
    source: str,
) -> ArchiveArtifact:
    """Экспортировать current canonical dataset в content-addressed Parquet archive.

    Args:
        session: Session committed operational DB, доступная только VPS export job.
        tournament: Tournament-scoped canonical dataset.
        archive_root: Local staging root, соответствующий Object Storage prefix.
        run_id: Stable scheduler run identity.
        config_id: Immutable identity конфигурации full refresh.
        source: Идентификатор provider source без endpoint/credential.

    Returns:
        Проверенный immutable archive artifact.
    """
    result = session.execute(
        select(CanonicalEvent, CanonicalEventRevision)
        .join(
            CanonicalEventRevision,
            (CanonicalEventRevision.canonical_event_id == CanonicalEvent.id)
            & (CanonicalEventRevision.revision_sha256 == CanonicalEvent.current_revision_sha256),
        )
        .where(CanonicalEvent.tournament == tournament)
    ).all()
    rows = [
        {
            "sport": event.sport,
            "tournament": event.tournament,
            "source": event.source,
            "source_event_id": event.source_event_id,
            "scheduled_at": event.scheduled_at,
            "status": event.status,
            "revision_sha256": revision.revision_sha256,
            "payload_json": revision.payload_json,
            "result_json": revision.result_json,
            "source_observed_at": revision.source_observed_at,
        }
        for event, revision in result
    ]
    if not rows:
        raise ValueError(f"Canonical snapshot пуст для tournament={tournament}")
    snapshot_id = _snapshot_id(rows)
    with tempfile.TemporaryDirectory(prefix=f"canonical-export-{tournament}-") as directory:
        stage = Path(directory)
        partition = stage / "partitions" / f"tournament={tournament}"
        partition.mkdir(parents=True)
        pd.DataFrame(rows).to_parquet(partition / "canonical_events.parquet", index=False)
        return archive_snapshot(
            stage,
            archive_root,
            provenance={
                "schema_version": "1",
                "run_id": run_id,
                "config_id": config_id,
                "source": source,
                "data_snapshot_id": snapshot_id,
            },
        )
