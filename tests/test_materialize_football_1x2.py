"""Материализация трёх исходов одного рынка winner 1X2."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from omegaconf import DictConfig, OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.bot.handlers.predict import _format_upcoming_line, _upcoming_query_params
from sports_forecast.materialize import (
    _aggregate_football_1x2_predictions,
    materialize_predictions,
)
from sports_forecast.predict import predict_single
from sports_forecast.service.db.models import Base, Prediction
from sports_forecast.service.routers import predictions as predictions_router


def test_long_1x2_keeps_draw_and_skips_only_bad_event() -> None:
    frame = pd.DataFrame(
        {
            "id": ["a", "a", "b", "b"],
            "datetime": ["2026-10-15"] * 4,
            "is_home": [1, 0, 1, 0],
            "pl": ["A", "B", "C", "D"],
        }
    )
    probabilities = np.array([[0.6, 0.4], [0.7, 0.3], [0.3, 0.7], [0.6, 0.4]])
    result, rejected = _aggregate_football_1x2_predictions(
        frame, probabilities, np.array([0, 1]), strategy="football_long_binary"
    )
    assert result.match_id.tolist() == ["a"]
    assert json.loads(result.iloc[0].predictions_json) == {
        "home_win": 0.4,
        "draw": 0.3,
        "away_win": 0.3,
    }
    assert rejected.match_id.tolist() == ["b"]
    assert rejected.reason.tolist() == ["negative_draw_residual"]


def test_wide_1x2_maps_permuted_classes() -> None:
    frame = pd.DataFrame({"id": ["a"], "datetime": ["2026-10-15"], "pl": ["A"], "opp": ["B"]})
    result, rejected = _aggregate_football_1x2_predictions(
        frame,
        np.array([[0.2, 0.5, 0.3]]),
        np.array([2, 0, 1]),
        strategy="football_wide_multiclass",
    )
    assert rejected.empty
    assert json.loads(result.iloc[0].predictions_json) == {
        "home_win": 0.5,
        "draw": 0.3,
        "away_win": 0.2,
    }


def _candidate_cfg(strategy: str) -> DictConfig:
    data_format = "long" if strategy == "football_long_binary" else "wide"
    return OmegaConf.create(
        {
            "tournament": {"name": "football_top_leagues"},
            "market": {"name": "winner"},
            "market_spec": {"name": "winner_1x2", "data_format": data_format},
            "model_strategy": {"name": strategy, "data_format": data_format},
            "algorithm": {"name": "catboost"},
            "features": {"name": "basic"},
            "paths": {
                "models_dir": "models",
                "processed_dir": "data/processed",
                "predictions_dir": "data/predictions",
            },
        }
    )


def _candidate_input(root: Path, strategy: str) -> None:
    scheduled = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    model_dir = root / "models/football_top_leagues/winner_1x2/catboost_basic" / strategy
    model_dir.mkdir(parents=True)
    (model_dir / f"{strategy}_shadow.cbm").touch()
    (model_dir / "features.txt").write_text("f_test", encoding="utf-8")
    processed_dir = root / "data/processed/football_top_leagues"
    processed_dir.mkdir(parents=True, exist_ok=True)
    if strategy == "football_long_binary":
        frame = pd.DataFrame(
            {
                "id": ["match-1", "match-1"],
                "datetime": [scheduled] * 2,
                "status": ["upcoming"] * 2,
                "is_home": [1, 0],
                "pl": ["A", "B"],
                "f_test": [1.0, 2.0],
                "pl_points": [None, None],
                "opp_points": [None, None],
            }
        )
        data_format = "long"
    else:
        frame = pd.DataFrame(
            {
                "id": ["match-1"],
                "datetime": [scheduled],
                "status": ["upcoming"],
                "pl": ["A"],
                "opp": ["B"],
                "f_test": [1.0],
                "home_points": [None],
                "away_points": [None],
            }
        )
        data_format = "wide"
    inference_path = processed_dir / f"inference_{data_format}.parquet"
    frame.to_parquet(inference_path, index=False)
    inference_path.with_suffix(".snapshot.json").write_text(
        json.dumps(
            {
                "source": "smart_tables",
                "observed_at": datetime.now(UTC).isoformat(),
                "sha256": sha256(inference_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


def test_local_materialization_keeps_both_1x2_candidates_separate(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for strategy, classes, probabilities in (
            ("football_long_binary", [0, 1], [[0.6, 0.4], [0.7, 0.3]]),
            ("football_wide_multiclass", [2, 0, 1], [[0.2, 0.5, 0.3]]),
        ):
            _candidate_input(tmp_path, strategy)
            model = MagicMock()
            model.classes_ = np.asarray(classes)
            model.predict_proba.return_value = np.asarray(probabilities)
            with (
                patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path),
                patch("sports_forecast.materialize.load_model_from_path", return_value=model),
            ):
                assert materialize_predictions(
                    _candidate_cfg(strategy), version="shadow", session=session
                )
        session.flush()
        rows = session.query(Prediction).order_by(Prediction.source_namespace).all()
        assert [row.source_namespace for row in rows] == [
            "local_test/football_long_binary",
            "local_test/football_wide_multiclass",
        ]
        assert [json.loads(row.predictions_json) for row in rows] == [
            {"home_win": 0.4, "draw": 0.3, "away_win": 0.3},
            {"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
        ]
        app = FastAPI()
        app.include_router(predictions_router.public_router)
        with patch.object(predictions_router, "get_session", return_value=nullcontext(session)):
            response = TestClient(app).get(
                "/predict/upcoming/football_top_leagues",
                params={
                    "market": "winner",
                    "market_spec": "winner_1x2",
                    "hours": _upcoming_query_params(
                        "football_top_leagues",
                        OmegaConf.create({"bot": {"club_test_hours": 168}}),
                    )["hours"],
                    "live_pinnacle": "false",
                },
            )
        assert response.status_code == 200
        items = response.json()["predictions"]
        assert len(items) == 2
        cards = [_format_upcoming_line(item) for item in items]
        assert any("1X2 (бинарная): П1 0.400 | Х 0.300 | П2 0.300" in card for card in cards)
        assert any("1X2 (многоклассовая): П1 0.500 | Х 0.300 | П2 0.200" in card for card in cards)


def test_local_materialization_rejects_non_test_sqlite(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'production.sqlite'}")
    with Session(engine) as session, patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path):
        assert not materialize_predictions(
            _candidate_cfg("football_wide_multiclass"), version="shadow", session=session
        )


def test_local_materialization_rejects_old_upcoming(tmp_path: Path) -> None:
    strategy = "football_wide_multiclass"
    _candidate_input(tmp_path, strategy)
    inference_path = tmp_path / "data/processed/football_top_leagues/inference_wide.parquet"
    frame = pd.read_parquet(inference_path)
    frame["datetime"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    frame.to_parquet(inference_path, index=False)
    manifest_path = inference_path.with_suffix(".snapshot.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = sha256(inference_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    model = MagicMock()
    model.classes_ = np.array([0, 1, 2])
    model.predict_proba.return_value = np.array([[0.5, 0.3, 0.2]])
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with (
        Session(engine) as session,
        patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path),
        patch("sports_forecast.materialize.load_model_from_path", return_value=model),
    ):
        with pytest.raises(ValueError, match="будущей даты"):
            materialize_predictions(_candidate_cfg(strategy), version="shadow", session=session)
        assert session.query(Prediction).count() == 0


def test_predict_single_rejects_1x2_without_aggregation() -> None:
    assert not predict_single(_candidate_cfg("football_wide_multiclass"), version="shadow")
