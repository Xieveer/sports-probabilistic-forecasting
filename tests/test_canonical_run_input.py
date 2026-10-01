"""Проверки границы canonical → immutable archive → model input."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from omegaconf import OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sports_forecast.orchestration.canonical_full_refresh import run_full_refresh
from sports_forecast.orchestration.canonical_run_input import (
    PreparedRunInput,
    _fail_current_stage,
    load_prepared_input,
    prepare_run_input,
)
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.repository import DataCycleRunRepository


RUN_ID = "00000000-0000-4000-8000-000000000034"


def test_prepared_input_requires_archive_sync_and_pins_rows(tmp_path: Path) -> None:
    """Расчёт видит архивированный snapshot лишь после подтверждения sync."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_csv = source_root / "current.csv"
    scheduled = datetime.now(UTC) + timedelta(days=1)
    source_csv.write_text(
        "id,datetime,match_is_end,game_state,game_type,home_team,away_team\n"
        f"1,{scheduled.isoformat()},0,FUT,regular,NYR,BOS\n",
        encoding="utf-8",
    )
    odds = source_root / "odds"
    odds.mkdir()
    pd.DataFrame(
        [{"game_date": "2026-10-01", "pinnacle_winner_withOT_home_close": 2.1}]
    ).to_parquet(odds / "pinnacle_odds.parquet")
    (odds / "refresh_state.json").write_text("{}", encoding="utf-8")
    archive_root = tmp_path / "archive"
    try:
        with get_session(engine=engine) as session:
            cycle = DataCycleRunRepository(session)
            cycle.create(run_id=RUN_ID, tournament="nhl", reason="scheduled")
            cycle.start_stage(RUN_ID, "calendar")
        with (
            patch(
                "sports_forecast.orchestration.canonical_run_input.get_session",
                side_effect=lambda: get_session(engine=engine),
            ),
            patch(
                "sports_forecast.orchestration.canonical_run_input.validate_prediction_result_freshness",
                return_value=SimpleNamespace(is_valid=True),
            ),
        ):
            descriptor = prepare_run_input(
                run_id=RUN_ID,
                source_csv=source_csv,
                archive_root=archive_root,
                refreshed_at=datetime.now(UTC),
                config_id="sha256:" + "a" * 64,
            )
            payload = json.loads(descriptor.read_text(encoding="utf-8"))
            assert payload["run_id"] == RUN_ID
            with pytest.raises(ValueError, match="Object Storage sync"):
                load_prepared_input(run_id=RUN_ID, archive_root=archive_root)
            with get_session(engine=engine) as session:
                cycle = DataCycleRunRepository(session)
                cycle.finish_stage(RUN_ID, "archive_sync", status="success")
            source_csv.write_text("tampered", encoding="utf-8")
            prepared = load_prepared_input(run_id=RUN_ID, archive_root=archive_root)
        assert len(prepared.rows) == 1
        assert prepared.rows[0]["id"] == "1"
        assert prepared.rows[0]["game_type"] == "regular"
        assert prepared.rows[0]["match_is_end"] == "0"
        assert prepared.canonical_artifact_id == payload["canonical_artifact_id"]
    finally:
        reset_engine()
        engine.dispose()


def test_prepared_worker_does_not_fetch_daily_odds(tmp_path: Path) -> None:
    """Worker после sync считает прогноз и оставляет daily odds пропущенными."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "deploy.yaml").write_text(
        "model:\n  algorithm: catboost\n  featureset: advanced\n", encoding="utf-8"
    )
    cfg = OmegaConf.create(
        {
            "tournament": {"name": "nhl"},
            "market": {"name": "winner_withOT"},
            "market_spec": {"name": "winner_withOT"},
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
    try:
        with get_session(engine=engine) as session:
            cycle = DataCycleRunRepository(session)
            cycle.create(run_id=RUN_ID, tournament="nhl", reason="scheduled")
            for stage in ("calendar", "quality", "archive_sync"):
                cycle.start_stage(RUN_ID, stage)
                cycle.finish_stage(RUN_ID, stage, status="success")
        with (
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.get_session",
                side_effect=lambda: get_session(engine=engine),
            ),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_prepared_input",
                return_value=PreparedRunInput(
                    rows=[
                        {
                            "id": "1",
                            "datetime": datetime.now(UTC).isoformat(),
                            "match_is_end": "0",
                            "game_type": "regular",
                        }
                    ],
                    canonical_artifact_id="sha256:" + "a" * 64,
                ),
            ) as prepared,
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.load_current_model_bundle",
                return_value=MagicMock(path=bundle),
            ),
            patch("sports_forecast.orchestration.canonical_full_refresh.process_tournament"),
            patch("sports_forecast.orchestration.canonical_full_refresh.process_tournament_new"),
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.materialize_predictions",
                return_value=True,
            ) as materialize,
            patch(
                "sports_forecast.orchestration.canonical_full_refresh.run_nhl_future_odds_batch",
                side_effect=AssertionError("daily odds запрещены"),
            ),
        ):
            result = run_full_refresh(
                cfg,
                run_id=RUN_ID,
                runtime_root=tmp_path,
                app_version="1.2.12",
                refreshed_at=datetime.now(UTC),
                prepared_archive_root=tmp_path / "archive",
            )
        assert result.published is True
        prepared.assert_called_once()
        assert materialize.call_args.args[0].canonical_snapshot_id == "sha256:" + "a" * 64
        with get_session(engine=engine) as session:
            cycle = DataCycleRunRepository(session)
            run = cycle.get(RUN_ID)
            assert run is not None
            stages = {stage.stage: stage.status for stage in run.stages}
            assert stages["data_odds"] == "skipped"
            odds_stage = next(stage for stage in run.stages if stage.stage == "data_odds")
            assert json.loads(odds_stage.counts_json or "{}")["disabled"] == 1
            assert stages["predictions"] == "success"
            assert stages["publication"] == "success"
            cycle.finish_run(
                RUN_ID,
                status="auto",
                required_stages={
                    "calendar",
                    "quality",
                    "archive_sync",
                    "predictions",
                    "publication",
                },
            )
            assert run.status == "success"
    finally:
        reset_engine()
        engine.dispose()


def test_failed_archive_stage_has_specific_terminal_code() -> None:
    """Неудача на границе архива не допускает последующий расчёт."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            cycle = DataCycleRunRepository(session)
            cycle.create(run_id=RUN_ID, tournament="nhl", reason="scheduled")
            for stage in ("calendar", "quality"):
                cycle.start_stage(RUN_ID, stage)
                cycle.finish_stage(RUN_ID, stage, status="success")
            cycle.start_stage(RUN_ID, "archive_sync")
        with patch(
            "sports_forecast.orchestration.canonical_run_input.get_session",
            side_effect=lambda: get_session(engine=engine),
        ):
            _fail_current_stage(RUN_ID)
        with get_session(engine=engine) as session:
            run = DataCycleRunRepository(session).get(RUN_ID)
            assert run is not None
            assert run.status == "failed"
            assert run.failure_code == "archive_sync_failed"
            assert {stage.stage: stage.status for stage in run.stages}["predictions"] == "skipped"
    finally:
        reset_engine()
        engine.dispose()
