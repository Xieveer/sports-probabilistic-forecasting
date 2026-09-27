"""Контракты full-history refresh из canonical store."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from omegaconf import OmegaConf
from sqlalchemy import create_engine

from sports_forecast.deploy.model_bundle import BundleVerificationError
from sports_forecast.orchestration.canonical_full_refresh import _load_bundle_features_config
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import (
    CanonicalEvent,
    CanonicalEventRevision,
    OddsAcquisitionAttempt,
    OddsObservation,
    Prediction,
    TournamentPublicationState,
    WorkerExecution,
)
from sports_forecast.service.db.repository import DataCycleRunRepository, PredictionRepository


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


@pytest.mark.parametrize(
    ("contract", "runtime_algorithm"),
    [
        ({"algorithm": "catboost", "featureset": "missing_featureset"}, "catboost"),
        ({"algorithm": "other_algorithm", "featureset": "advanced"}, "catboost"),
    ],
)
def test_bundle_feature_contract_rejects_mismatch_before_feature_generation(
    tmp_path: Path, contract: dict[str, str], runtime_algorithm: str
) -> None:
    """Неизвестный featureset или другой algorithm отклоняется до feature generation."""
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "deploy.yaml").write_text(
        f"model:\n  algorithm: {contract['algorithm']}\n  featureset: {contract['featureset']}\n",
        encoding="utf-8",
    )

    with pytest.raises(BundleVerificationError):
        _load_bundle_features_config(bundle_path, algorithm=runtime_algorithm)


def test_full_refresh_rebuilds_from_canonical_snapshot_not_existing_processed(
    tmp_path: Path,
) -> None:
    """Runner передаёт full canonical history в clean/features перед inference."""
    from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    refreshed_at = datetime.now(UTC)
    scheduled_at = refreshed_at + timedelta(days=1)
    try:
        with get_session(engine=engine) as session:
            event = CanonicalEvent(
                sport="ice_hockey",
                tournament="nhl",
                source="nhl_web_api",
                source_event_id="1",
                scheduled_at=scheduled_at.replace(tzinfo=None),
                status="upcoming",
                current_revision_sha256="a" * 64,
            )
            session.add(event)
            session.flush()
            session.add(
                CanonicalEventRevision(
                    canonical_event_id=event.id,
                    revision_sha256="a" * 64,
                    payload_json=json.dumps({"id": "1", "datetime": scheduled_at.isoformat()}),
                    result_json="{}",
                    source_observed_at=datetime(2026, 8, 13, tzinfo=UTC),
                )
            )
            cycle_repository = DataCycleRunRepository(session)
            cycle_repository.create(run_id="nhl-20260814", tournament="nhl", reason="scheduled")
            cycle_repository.start_stage("nhl-20260814", "calendar")

        source_csv = tmp_path / "source.csv"
        source_csv.write_text(
            "id,datetime,match_is_end,game_state,home_team,away_team\n"
            f"1,{scheduled_at.isoformat()},0,PRE,NYR,BOS\n",
            encoding="utf-8",
        )

        clean = MagicMock()
        features = MagicMock()
        materialize = MagicMock(return_value=True)
        bundle_path = tmp_path / "bundle"
        bundle_path.mkdir()
        (bundle_path / "deploy.yaml").write_text(
            "model:\n  algorithm: catboost\n  featureset: advanced\n", encoding="utf-8"
        )
        odds_provider = MagicMock()
        odds_provider.fetch_future_nhl_odds.return_value = []
        odds_provider.last_quota.return_value.requests_remaining = 20
        odds_provider.last_quota.return_value.requests_used = 3
        with (
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.get_session",
                side_effect=lambda: get_session(engine=engine),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_current_model_bundle",
                return_value=MagicMock(path=bundle_path),
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
            patch(
                "sports_forecast.orchestration.future_odds.OddsApiClient",
                return_value=odds_provider,
            ),
        ):
            result = run_full_refresh(
                _cfg(),
                run_id="nhl-20260814",
                runtime_root=tmp_path,
                app_version="1.1.0",
                refreshed_at=refreshed_at,
                source_csv=source_csv,
            )

        assert result.published is True
        assert clean.call_count == 1
        assert features.call_count == 1
        assert features.call_args.args[3].name == "advanced"
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
            cycle = DataCycleRunRepository(session).get("nhl-20260814")
            assert cycle is not None
            stages = {stage.stage: stage for stage in cycle.stages}
            statuses = {name: stage.status for name, stage in stages.items()}
            assert statuses["calendar"] == "success"
            assert json.loads(stages["calendar"].counts_json or "{}") == {
                "changed_events": 1,
                "events": 1,
                "events_found": 1,
                "new_events": 0,
            }
            assert statuses["data_odds"] == "partial_success"
            assert statuses["quality"] == "success"
            assert statuses["predictions"] == "success"
            assert statuses["publication"] == "success"
            publication_counts = json.loads(stages["publication"].counts_json or "{}")
            assert publication_counts["eligible_events"] == 1
            assert publication_counts["predictions_ready"] == 0
            assert publication_counts["odds_ready"] == 0
            assert publication_counts["fully_ready_events"] == 0
            odds_attempt = session.query(OddsAcquisitionAttempt).one()
            assert odds_attempt.status == "success"
            assert odds_attempt.missing_events == 1
            assert odds_attempt.requests_remaining == 20
            cycle_repository = DataCycleRunRepository(session)
            cycle_repository.start_stage("nhl-20260814", "archive_sync")
            cycle_repository.finish_stage("nhl-20260814", "archive_sync", status="success")
            cycle_repository.finish_run(
                "nhl-20260814",
                status="auto",
                required_stages=frozenset(
                    {"calendar", "quality", "predictions", "publication", "archive_sync"}
                ),
            )
            finished_run = cycle_repository.get("nhl-20260814")
            assert finished_run is not None and finished_run.status == "partial_success"
            finished_summary = json.loads(finished_run.summary_json or "{}")
            assert finished_summary["last_successful_updates"]["odds"]["status"] == "unknown"
            assert finished_summary["readiness_as_of"]["status"] == "known"
            assert finished_summary["readiness_as_of"]["source"] == "publication_stage.completed_at"
            assert finished_summary["readiness_as_of"]["at"] == stages[
                "publication"
            ].completed_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    finally:
        reset_engine()


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


def test_publication_transaction_rejects_stale_executor_generation(monkeypatch) -> None:
    """Generation change after earlier stages is rejected at publication boundary."""
    from sports_forecast.orchestration.canonical_full_refresh import (
        _assert_run_publication_owner,
    )
    from sports_forecast.service.db.models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with get_session(engine=engine) as session:
        repository = DataCycleRunRepository(session)
        repository.create(run_id="run-stale-publication", tournament="nhl", reason="scheduled")
        repository.claim_executor(
            "run-stale-publication",
            owner_id="aabbccdd00112233aabbccdd00112233",
            at=datetime(2026, 9, 26, 10, tzinfo=UTC),
        )

    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", "aabbccdd00112233aabbccdd00112233")
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", "2")
    with (
        get_session(engine=engine) as session,
        pytest.raises(RuntimeError, match="generation fenced"),
    ):
        _assert_run_publication_owner(session, "run-stale-publication")
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
            "sports_forecast.orchestration.canonical_full_refresh.refresh_nhl_canonical_with_summary_from_csv"
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


def test_readiness_producers_use_policy_window_and_run_timestamp() -> None:
    """Readiness denominators use a fixed 30-day policy window, not all DB rows."""
    from sports_forecast.orchestration.canonical_full_refresh import _readiness_counts

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    run_at = datetime(2026, 9, 26, 8, tzinfo=UTC)
    try:
        with get_session(engine=engine) as session:
            for event_id, day in (("inside", 29), ("boundary", 30), ("outside", 31)):
                session.add(
                    CanonicalEvent(
                        sport="ice_hockey",
                        tournament="nhl",
                        source="nhl_web_api",
                        source_event_id=event_id,
                        scheduled_at=(run_at + timedelta(days=day)).replace(tzinfo=None),
                        status="scheduled",
                        current_revision_sha256=event_id.ljust(64, "0"),
                    )
                )
            session.flush()
            counts = _readiness_counts(session, tournament="nhl", at=run_at)

        assert counts == {
            "eligible_events": 1,
            "odds_eligible_events": 1,
            "predictions_ready": 0,
            "odds_ready": 0,
            "fully_ready_events": 0,
            "partially_ready_events": 0,
            "errors": 0,
        }
    finally:
        reset_engine()
        engine.dispose()


def test_football_fixture_uses_shared_producer_with_its_own_policy(monkeypatch) -> None:
    """Contract fixture has a shorter 1X2 policy but uses the shared counter producer."""
    from sports_forecast.orchestration import canonical_full_refresh
    from sports_forecast.orchestration.canonical_full_refresh import _readiness_counts

    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    run_at = datetime(2026, 9, 26, 8, tzinfo=UTC)
    football_policy = {
        "eligibility_window_days": 14,
        "prediction_freshness_hours": 12,
        "odds_freshness_hours": 3,
        "preparation_deadline_hours": 4,
        "prediction_markets": [{"market": "winner", "market_spec": "1x2"}],
        "odds_markets": [{"market": "winner", "market_spec": "1x2", "bookmaker": "examplebook"}],
    }
    monkeypatch.setattr(
        canonical_full_refresh,
        "load_readiness_policy",
        lambda tournament: football_policy if tournament == "football_fixture" else None,
    )
    try:
        with get_session(engine=engine) as session:
            event = CanonicalEvent(
                sport="football",
                tournament="football_fixture",
                source="fixture_source",
                source_event_id="football-1",
                scheduled_at=(run_at + timedelta(days=13)).replace(tzinfo=None),
                status="scheduled",
                current_revision_sha256="f" * 64,
                home_participant="Home",
                away_participant="Away",
            )
            session.add(event)
            session.flush()
            session.add(
                Prediction(
                    match_id="football-1",
                    tournament="football_fixture",
                    market="winner",
                    market_spec="1x2",
                    model_version="fixture-model",
                    algorithm="fixture",
                    featureset="fixture",
                    predictions_json='{"home_win":0.5,"draw":0.25,"away_win":0.25}',
                    prediction_ts=run_at.replace(tzinfo=None),
                    status="ok",
                )
            )
            session.add(
                OddsObservation(
                    canonical_event_id=event.id,
                    market="winner",
                    market_spec="1x2",
                    bookmaker="examplebook",
                    event_scheduled_at=(run_at + timedelta(days=13)).replace(tzinfo=None),
                    event_home_participant="Home",
                    event_away_participant="Away",
                    observed_at=(run_at - timedelta(hours=1)).replace(tzinfo=None),
                    retrieved_at=run_at.replace(tzinfo=None),
                    values_json='{"home":2.0,"draw":3.2,"away":4.0}',
                    source="fixture_feed",
                )
            )
            session.add(
                CanonicalEvent(
                    sport="football",
                    tournament="football_fixture",
                    source="fixture_source",
                    source_event_id="football-outside-window",
                    scheduled_at=(run_at + timedelta(days=15)).replace(tzinfo=None),
                    status="scheduled",
                    current_revision_sha256="e" * 64,
                )
            )
            session.flush()

            counts = _readiness_counts(session, tournament="football_fixture", at=run_at)

        assert counts == {
            "eligible_events": 1,
            "odds_eligible_events": 1,
            "predictions_ready": 1,
            "odds_ready": 1,
            "fully_ready_events": 1,
            "partially_ready_events": 0,
            "errors": 0,
        }
    finally:
        reset_engine()
        engine.dispose()
