"""Контракт immutable Parquet export current canonical dataset."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.deploy.canonical_snapshot import export_canonical_snapshot
from sports_forecast.service.db.models import Base, CanonicalEvent, CanonicalEventRevision


def test_export_contains_current_canonical_partition_and_safe_provenance(tmp_path: Path) -> None:
    """Export не включает stale revision и manifest не хранит provider payload."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        event = CanonicalEvent(
            sport="ice_hockey",
            tournament="nhl",
            source="nhl_web_api",
            source_event_id="1",
            scheduled_at=datetime(2026, 8, 15, tzinfo=UTC),
            status="upcoming",
            current_revision_sha256="b" * 64,
        )
        session.add(event)
        session.flush()
        session.add_all(
            [
                CanonicalEventRevision(
                    canonical_event_id=event.id,
                    revision_sha256="a" * 64,
                    payload_json='{"stale":true}',
                    result_json="{}",
                    source_observed_at=datetime(2026, 8, 14, tzinfo=UTC),
                ),
                CanonicalEventRevision(
                    canonical_event_id=event.id,
                    revision_sha256="b" * 64,
                    payload_json='{"current":true}',
                    result_json="{}",
                    source_observed_at=datetime(2026, 8, 15, tzinfo=UTC),
                ),
            ]
        )
        session.commit()
        artifact = export_canonical_snapshot(
            session,
            tournament="nhl",
            archive_root=tmp_path / "archive",
            run_id="run-1",
            config_id="cfg-1",
            source="nhl_web_api",
        )

    manifest = json.loads((artifact.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provenance"]["run_id"] == "run-1"
    assert "current" not in json.dumps(manifest)
    exported = pd.read_parquet(
        artifact.path / "partitions" / "tournament=nhl" / "canonical_events.parquet"
    )
    assert exported["revision_sha256"].tolist() == ["b" * 64]
