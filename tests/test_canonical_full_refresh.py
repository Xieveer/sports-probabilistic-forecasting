"""Контракты full-history refresh из canonical store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf
from sqlalchemy import create_engine

from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import (
    CanonicalEvent,
    CanonicalEventRevision,
    Prediction,
    TournamentPublicationState,
    WorkerExecution,
)
from sports_forecast.service.db.repository import PredictionRepository


def _cfg() -> object:
    return OmegaConf.create(
        {
            "tournament": {"name": "nhl"},
            "market": {"name": "winner_withOT"},
            "market_spec": {"name": "winner_withOT", "data_format": "long"},
            "algorithm": {"name": "catboost"},
            "features": {"name": "basic"},
            "paths": {
                "raw_dir": "data/raw",
                "interim_dir": "data/interim",
                "processed_dir": "data/processed",
                "predictions_dir": "data/predictions",
                "models_dir": "models",
            },
        }
    )


def test_full_refresh_rebuilds_from_canonical_snapshot_not_existing_processed(
    tmp_path: Path,
) -> None:
    """Runner передаёт full canonical history в clean/features перед inference."""
    from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            event = CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="1",
                scheduled_at=datetime(2026, 8, 14, tzinfo=UTC),
                status="upcoming",
                current_revision_sha256="a" * 64,
            )
            session.add(event)
            session.flush()
            session.add(
                CanonicalEventRevision(
                    canonical_event_id=event.id,
                    revision_sha256="a" * 64,
                    payload_json=json.dumps({"id": "1", "datetime": "2026-08-14T00:00:00Z"}),
                    result_json="{}",
                    source_observed_at=datetime(2026, 8, 13, tzinfo=UTC),
                )
            )

        clean = MagicMock()
        features = MagicMock()
        materialize = MagicMock(return_value=True)
        with (
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.get_session",
                side_effect=lambda: get_session(engine=engine),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_current_model_bundle",
                return_value=MagicMock(path=tmp_path / "bundle"),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_tournament_config",
                side_effect=AssertionError("nested Hydra compose недопустим внутри CLI"),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.process_tournament",
                clean,
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.process_tournament_new",
                features,
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.materialize_predictions",
                materialize,
            ),
        ):
            result = run_full_refresh(
                _cfg(),
                run_id="nhl-20260814",
                runtime_root=tmp_path,
                app_version="1.1.0",
                refreshed_at=datetime(2026, 8, 14, tzinfo=UTC),
            )

        assert result.published is True
        assert clean.call_count == 1
        assert features.call_count == 1
        raw_path = clean.call_args.args[0] / "matches.parquet"
        assert raw_path.name == "matches.parquet"
        assert raw_path.parent.name == "nhl"
        assert raw_path.parent != tmp_path / "data" / "processed" / "nhl"
        materialize.assert_called_once()
        assert materialize.call_args.kwargs["version"] == "prod"
        assert materialize.call_args.kwargs["session"] is not None
        with get_session(engine=engine) as session:
            state = session.query(TournamentPublicationState).one()
            execution = session.query(WorkerExecution).one()
            assert state.status == "public"
            assert execution.status == "succeeded"
    finally:
        reset_engine()
        engine.dispose()


def test_blocked_publication_is_hidden_from_upcoming_predictions() -> None:
    """Неуспешный refresh сохраняет audit-row, но скрывает его от bot/API reader."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            session.add(
                Prediction(
                    match_id="1",
                    tournament="nhl",
                    market="winner",
                    market_spec="winner_withOT",
                    model_version="x",
                    algorithm="x",
                    featureset="x",
                    predictions_json="{}",
                    match_datetime=datetime(2026, 8, 15, tzinfo=UTC),
                )
            )
            session.add(
                TournamentPublicationState(
                    tournament="nhl", market="winner", market_spec="winner_withOT", status="blocked"
                )
            )
        with get_session(engine=engine) as session:
            repository = PredictionRepository(session)
            result = repository.get_upcoming_predictions(
                tournament="nhl",
                market="winner",
                market_spec="winner_withOT",
                now_utc=datetime(2026, 8, 14, tzinfo=UTC),
            )
        assert result == []
        with get_session(engine=engine) as session:
            repository = PredictionRepository(session)
            assert repository.get_latest_prediction("1", "winner", "winner_withOT") is None
            assert repository.get_predictions_by_match("1") == []
    finally:
        reset_engine()
        engine.dispose()


def test_full_refresh_blocks_slice_when_expired_prediction_has_no_result(tmp_path: Path) -> None:
    """Freshness gate останавливает run до bundle verification и rebuild."""
    from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            session.add(
                Prediction(
                    match_id="expired",
                    tournament="nhl",
                    market="winner_withOT",
                    market_spec="winner_withOT",
                    model_version="x",
                    algorithm="x",
                    featureset="x",
                    predictions_json="{}",
                    match_datetime=datetime(2026, 8, 14, tzinfo=UTC),
                )
            )
        bundle = MagicMock()
        with (
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.get_session",
                side_effect=lambda: get_session(engine=engine),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_current_model_bundle",
                bundle,
            ),
        ):
            result = run_full_refresh(
                _cfg(),
                run_id="stale",
                runtime_root=tmp_path,
                app_version="1.1.0",
                refreshed_at=datetime(2026, 8, 15, tzinfo=UTC),
            )
        assert result.failure_code == "canonical_freshness_failed"
        bundle.assert_not_called()
        with get_session(engine=engine) as session:
            assert (
                PredictionRepository(session).get_upcoming_predictions(
                    tournament="nhl",
                    market="winner_withOT",
                    market_spec="winner_withOT",
                    now_utc=datetime(2026, 8, 13, tzinfo=UTC),
                )
                == []
            )
    finally:
        reset_engine()
        engine.dispose()


def test_full_refresh_applies_provider_snapshot_before_freshness_gate(tmp_path: Path) -> None:
    """Перед rebuild runner применяет переданный provider CSV к canonical store."""
    from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    source_csv = tmp_path / "source.csv"
    source_csv.write_text("id,datetime,match_is_end\n1,2026-08-15T00:00:00Z,0\n", encoding="utf-8")
    with (
        patch(
            "sports_forecast.orchestration.canonical_full_refresh.get_session",
            side_effect=lambda: get_session(engine=engine),
        ),
        patch(
            "sports_forecast.orchestration.canonical_full_refresh.refresh_nhl_canonical_from_csv"
        ) as refresh,
        patch(
            "sports_forecast.orchestration.canonical_full_refresh.load_current_model_bundle",
            side_effect=ValueError(),
        ),
    ):
        result = run_full_refresh(
            _cfg(),
            run_id="source",
            runtime_root=tmp_path,
            app_version="1.1.0",
            refreshed_at=datetime(2026, 8, 15, tzinfo=UTC),
            source_csv=source_csv,
        )
    assert result.failure_code == "canonical_rebuild_failed"
    refresh.assert_called_once()
