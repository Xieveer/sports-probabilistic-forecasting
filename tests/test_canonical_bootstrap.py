"""Контракты immutable initial bootstrap canonical NHL history."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.deploy.canonical_bootstrap import (
    build_nhl_bootstrap_bundle,
    import_nhl_bootstrap_bundle,
    refresh_nhl_canonical_from_csv,
)
from sports_forecast.deploy.serving_data import ArchiveVerificationError
from sports_forecast.service.db.models import (
    Base,
    BootstrapImport,
    CanonicalEvent,
    CanonicalEventRevision,
    RefreshWatermark,
)


def _write_nhl_source_csv(path: Path) -> None:
    path.write_text(
        "id,datetime,match_is_end,home_score_ft,away_score_ft,match_end,home_team,away_team\n"
        "202401,2024-01-01T20:00:00Z,1,3,2,REG,Home A,Away A\n"
        "202402,2024-01-02T20:00:00Z,0,,,,Home B,Away B\n",
        encoding="utf-8",
    )


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_verified_nhl_bootstrap_imports_canonical_history_once(tmp_path: Path) -> None:
    """Повтор того же verified bundle не создаёт второй набор event/revision."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    session = _session()
    try:
        first = import_nhl_bootstrap_bundle(bundle.path, session)
        second = import_nhl_bootstrap_bundle(bundle.path, session)

        assert first.imported is True
        assert first.events_count == 2
        assert second.imported is False
        assert second.events_count == 2
        assert session.scalars(select(CanonicalEvent)).all()
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 2
        assert len(session.scalars(select(BootstrapImport)).all()) == 1
        watermark = session.scalar(select(RefreshWatermark))
        assert watermark is not None
        assert watermark.tournament == "nhl"
        assert watermark.snapshot_id == bundle.artifact_id
    finally:
        session.close()


def test_tampered_bootstrap_bundle_does_not_write_partial_history(tmp_path: Path) -> None:
    """Checksum проверяется до первой DB-записи canonical history."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    events_path = bundle.path / "canonical_events.jsonl"
    original = events_path.read_text(encoding="utf-8")
    events_path.write_text(original.replace("Home A", "Xome A", 1), encoding="utf-8")
    session = _session()
    try:
        with pytest.raises(ArchiveVerificationError, match="checksum"):
            import_nhl_bootstrap_bundle(bundle.path, session)

        assert session.scalars(select(CanonicalEvent)).all() == []
        assert session.scalars(select(BootstrapImport)).all() == []
    finally:
        session.close()


def test_refresh_csv_creates_new_revision_for_provider_correction(tmp_path: Path) -> None:
    """Incremental provider CSV меняет revision, не создавая второй canonical event."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    session = _session()
    try:
        import_nhl_bootstrap_bundle(bundle.path, session)
        source_csv.write_text(
            "id,datetime,match_is_end,home_score_ft,away_score_ft,match_end,home_team,away_team\n"
            "202401,2024-01-01T20:00:00Z,1,4,2,REG,Home A,Away A\n",
            encoding="utf-8",
        )
        assert refresh_nhl_canonical_from_csv(source_csv, session) == 1
        assert len(session.scalars(select(CanonicalEvent)).all()) == 2
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 3
    finally:
        session.close()
