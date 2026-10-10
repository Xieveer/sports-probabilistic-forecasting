"""Тесты для sports_forecast/materialize.py."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from omegaconf import OmegaConf
from sqlalchemy import create_engine

from sports_forecast.deploy.model_bundle import build_managed_model_bundle, build_model_bundle
from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.materialize import (
    _aggregate_long_predictions,
    _resolve_verified_model_provenance,
    materialize_predictions,
)
from sports_forecast.service.db.engine import get_session, init_db, reset_engine
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import ModelRegistryRepository, PredictionRepository


def _build_cfg() -> dict:
    return {
        "tournament": {"name": "uel_kz_1"},
        "market": {"name": "winner"},
        "market_spec": {"name": "winner", "data_format": "long"},
        "algorithm": {"name": "catboost"},
        "features": {"name": "basic"},
        "paths": {
            "models_dir": "models",
            "processed_dir": "data/processed",
            "predictions_dir": "data/predictions",
        },
    }


class TestMaterializePromotedContract:
    """Проверка прод-контракта materialize."""

    @patch("sports_forecast.materialize.load_model_from_path")
    @patch("sports_forecast.materialize.get_session")
    def test_uses_deploy_contract_for_prod(
        self,
        mock_get_session: MagicMock,
        mock_load_model: MagicMock,
        tmp_path: Path,
    ) -> None:
        cfg = OmegaConf.create(_build_cfg())

        promoted_dir = tmp_path / "models" / "uel_kz_1" / "winner" / "best"
        promoted_dir.mkdir(parents=True)
        (promoted_dir / "deploy.yaml").write_text(
            "model:\n  algorithm: lgbm\n  featureset: advanced\n",
            encoding="utf-8",
        )
        (promoted_dir / "model_prod.lgbm").touch()
        (promoted_dir / "features.txt").write_text("f_a\nf_b", encoding="utf-8")
        algorithm_cfg_dir = tmp_path / "conf" / "algorithm"
        algorithm_cfg_dir.mkdir(parents=True)
        (algorithm_cfg_dir / "lgbm.yaml").write_text(
            "name: lgbm\n_target_: sports_forecast.training.models.lgbm.LGBMModel\n",
            encoding="utf-8",
        )

        processed_dir = tmp_path / "data" / "processed" / "uel_kz_1"
        processed_dir.mkdir(parents=True)
        inference_df = pd.DataFrame(
            {
                "id": ["m1", "m1"],
                "side": ["h", "a"],
                "datetime": ["2026-01-01T12:00:00", "2026-01-01T12:00:00"],
                "pl_short_name_en": ["Home", "Away"],
                "f_a": [1.0, 2.0],
                "f_b": [3.0, 4.0],
                "odds_raw": [None, None],
            }
        )
        inference_df.to_parquet(processed_dir / "inference_long.parquet", index=False)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.2, 0.8], [0.6, 0.4]])
        mock_load_model.return_value = mock_model

        mock_repo = MagicMock()
        with_session = nullcontext(MagicMock())
        mock_get_session.return_value = with_session

        with (
            patch("sports_forecast.materialize.PredictionRepository", return_value=mock_repo),
            patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path),
        ):
            ok = materialize_predictions(cfg, version="prod")

        assert ok is True
        assert mock_load_model.call_args is not None
        algorithm_cfg = mock_load_model.call_args.args[0]
        assert str(algorithm_cfg.name) == "lgbm"

        assert mock_repo.publish_showcase.call_count == 1
        records = mock_repo.publish_showcase.call_args.args[0]
        assert len(records) == 1
        assert records[0]["algorithm"] == "lgbm"
        assert records[0]["featureset"] == "advanced"
        assert records[0]["model_version"] == "lgbm_advanced_prod"

    def test_prod_fails_without_deploy_contract(self, tmp_path: Path) -> None:
        cfg = OmegaConf.create(_build_cfg())

        with patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path):
            ok = materialize_predictions(cfg, version="prod")

        assert ok is False


def test_aggregate_long_uses_pl_when_pl_short_name_en_absent() -> None:
    """NHL long inference: идентификатор в ``pl``, без ``pl_short_name_en``."""
    df = pd.DataFrame(
        {
            "id": ["m1", "m1"],
            "side": ["h", "a"],
            "datetime": ["2026-05-14T00:00:00Z", "2026-05-14T00:00:00Z"],
            "pl": ["TOR", "OTT"],
            "f_x": [1.0, 2.0],
        }
    )
    proba = np.array([[0.3, 0.7], [0.55, 0.45]])
    out = _aggregate_long_predictions(df, proba)
    assert len(out) == 1
    assert out.iloc[0]["home_player"] == "TOR"
    assert out.iloc[0]["away_player"] == "OTT"


def test_aggregate_long_prefers_pl_short_name_en_over_pl() -> None:
    """Если задано короткое имя игрока, оно важнее аббревиатуры ``pl``."""
    df = pd.DataFrame(
        {
            "id": ["m1", "m1"],
            "side": ["h", "a"],
            "datetime": ["2026-01-01T12:00:00", "2026-01-01T12:00:00"],
            "pl": ["H_CODE", "A_CODE"],
            "pl_short_name_en": ["Home Star", "Away Star"],
            "f_a": [1.0, 2.0],
        }
    )
    proba = np.array([[0.2, 0.8], [0.6, 0.4]])
    out = _aggregate_long_predictions(df, proba)
    assert out.iloc[0]["home_player"] == "Home Star"
    assert out.iloc[0]["away_player"] == "Away Star"


def test_resolve_verified_model_provenance_matches_active_pointer(tmp_path: Path) -> None:
    """Managed provenance берётся из bundle после совпадения с active registry."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"model")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:football_nationals_winner:winner:immutable",
        app_version="1.2.15",
        source_commit="abc",
        release="test",
    )
    cfg = OmegaConf.create(
        {
            "model_pool": {"name": "football_nationals_winner"},
            "market_spec": {"name": "winner"},
            "runtime_model_bundle": str(bundle.path),
            "runtime_model_bundle_app_version": "1.2.15",
        }
    )
    registry = MagicMock()
    registry.get_active.return_value = MagicMock(
        model_identity="pool:football_nationals_winner:winner:immutable", is_managed=False
    )

    provenance = _resolve_verified_model_provenance(cfg, registry)

    assert provenance == (
        "football_nationals_winner",
        "pool:football_nationals_winner:winner:immutable",
        None,
    )


def test_managed_materialize_rejects_pointer_changed_during_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race после inference не меняет прежнюю валидную витрину."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"managed-model")
    bundle = build_managed_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:nhl:winner_withOT:old",
        app_version="1.2.15",
        model_pool="nhl",
        market_spec="winner_withOT",
        market_rules={"overtime": True, "shootout": True, "draw": False},
        outcomes=["home_win", "away_win"],
        feature_contract_id="feature-contract-v1",
        features=[{"name": "f1", "type": "float"}],
        transformations_version="v1",
        algorithm="lgbm",
        model_entrypoint="model.bin",
    )
    with get_session(engine=engine) as session:
        PredictionRepository(session).upsert_prediction(
            match_id="old-match",
            tournament="nhl",
            market="winner_withOT",
            market_spec="winner_withOT",
            predictions={"home_win": 0.6, "away_win": 0.4},
            model_version="previous",
            algorithm="lgbm",
            featureset="basic",
        )
        ModelRegistryRepository(session).promote_managed(
            model_pool="nhl",
            market_spec="winner_withOT",
            model_identity=bundle.model_identity,
            candidate_report_ref="reports/old.json",
            artifact_ref=bundle.bundle_id,
            bundle_id=bundle.bundle_id,
            managed_artifact_location=f"{bundle.bundle_id}/model.bin",
        )
    processed = tmp_path / "data" / "processed" / "nhl"
    processed.mkdir(parents=True)
    pd.DataFrame(
        {
            "id": ["new-match", "new-match"],
            "side": ["h", "a"],
            "datetime": ["2026-10-10T12:00:00"] * 2,
            "f1": [1.0, 2.0],
        }
    ).to_parquet(processed / "inference_long.parquet", index=False)
    algorithm_dir = tmp_path / "conf" / "algorithm"
    algorithm_dir.mkdir(parents=True)
    (algorithm_dir / "lgbm.yaml").write_text("name: lgbm\n", encoding="utf-8")
    cfg_data = _build_cfg()
    cfg_data.update(
        {
            "tournament": {"name": "nhl"},
            "market": {"name": "winner_withOT"},
            "market_spec": {"name": "winner_withOT", "data_format": "long"},
            "model_pool": {"name": "nhl"},
            "runtime_model_bundle_app_version": "1.2.15",
            "runtime_model_bundle_root": str(tmp_path / "bundles"),
        }
    )
    monkeypatch.setattr("sports_forecast.materialize.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "sports_forecast.materialize.get_session", lambda: get_session(engine=engine)
    )
    output_path = (
        tmp_path / "data" / "predictions" / "nhl" / "winner_withOT" / "predictions_prod.parquet"
    )
    output_path.parent.mkdir(parents=True)
    preserved_file = pd.DataFrame({"match_id": ["still-current"], "marker": [42]})
    preserved_file.to_parquet(output_path, index=False)

    class RacingModel:
        def predict_proba(self, _features: pd.DataFrame) -> np.ndarray:
            with get_session(engine=engine) as session:
                ModelRegistryRepository(session).promote_managed(
                    model_pool="nhl",
                    market_spec="winner_withOT",
                    model_identity="pool:nhl:winner_withOT:new",
                    candidate_report_ref="reports/new.json",
                    artifact_ref="sha256:new",
                    bundle_id="sha256:new",
                    managed_artifact_location="sha256:new/model.bin",
                )
            return np.array([[0.2, 0.8], [0.7, 0.3]])

    monkeypatch.setattr(
        "sports_forecast.materialize.load_model_from_path", lambda *_: RacingModel()
    )
    try:
        assert materialize_predictions(OmegaConf.create(cfg_data), version="prod") is False
        pd.testing.assert_frame_equal(pd.read_parquet(output_path), preserved_file)
        assert list(output_path.parent.glob(".*.tmp")) == []
        with get_session(engine=engine) as session:
            rows = session.query(Prediction).all()
        assert [(row.match_id, row.predictions_json, row.status) for row in rows] == [
            ("old-match", '{"home_win": 0.6, "away_win": 0.4}', "ok")
        ]
    finally:
        reset_engine()
        engine.dispose()


@pytest.mark.parametrize(
    "failure", ["identity", "missing_active", "missing_bundle", "corrupt", "app_version"]
)
@pytest.mark.parametrize("empty_input", [False, True])
def test_managed_materialize_rejects_invalid_contract_before_model_load(
    tmp_path: Path, monkeypatch, empty_input: bool, failure: str
) -> None:
    """Managed registry/bundle failures block inference and empty-input publication."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "deploy.yaml").write_text(
        "model:\n  algorithm: catboost\n  featureset: basic\n", encoding="utf-8"
    )
    (source / "model_prod.cbm").write_bytes(b"model")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="identity-b",
        app_version="1.2.15",
        source_commit="abc",
        release="test",
    )
    if failure == "corrupt":
        (bundle.path / "model_prod.cbm").write_bytes(b"tampered")
    processed = tmp_path / "data" / "processed" / "uel_kz_1"
    processed.mkdir(parents=True)
    frame = (
        pd.DataFrame()
        if empty_input
        else pd.DataFrame(
            {
                "id": ["new", "new"],
                "side": ["h", "a"],
                "datetime": ["2026-10-01"] * 2,
                "f1": [1.0, 2.0],
            }
        )
    )
    frame.to_parquet(processed / "inference_long.parquet", index=False)
    with get_session(engine=engine) as session:
        PredictionRepository(session).upsert_prediction(
            match_id="old",
            tournament="uel_kz_1",
            market="winner",
            market_spec="winner",
            predictions={"home_win": 0.6, "away_win": 0.4},
            model_version="old",
            algorithm="catboost",
            featureset="basic",
        )
    cfg_data = _build_cfg()
    cfg_data["model_pool"] = {"name": "pool"}
    cfg_data["runtime_model_bundle"] = str(
        tmp_path / "missing-bundle" if failure == "missing_bundle" else bundle.path
    )
    cfg_data["runtime_model_bundle_app_version"] = "2.0.0" if failure == "app_version" else "1.2.15"
    monkeypatch.setattr("sports_forecast.materialize.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "sports_forecast.materialize.find_model_file",
        lambda *_a, **_k: bundle.path / "model_prod.cbm",
    )
    registered_identity = "identity-b" if failure == "missing_active" else "identity-a"
    active = (
        None
        if failure == "missing_active"
        else MagicMock(model_identity=registered_identity, is_managed=False)
    )
    monkeypatch.setattr(
        "sports_forecast.materialize.ModelRegistryRepository",
        lambda _s: MagicMock(get_active=lambda *_a: active),
    )
    load_model = MagicMock()
    monkeypatch.setattr("sports_forecast.materialize.load_model_from_path", load_model)
    try:
        with get_session(engine=engine) as session:
            result = materialize_predictions(OmegaConf.create(cfg_data), session=session)
        assert result is False
        load_model.assert_not_called()
        with get_session(engine=engine) as session:
            rows = session.query(Prediction).all()
            assert [(row.match_id, row.status) for row in rows] == [("old", "ok")]
    finally:
        reset_engine()
        engine.dispose()


def test_external_materialization_failure_rolls_back_stale_transition(
    tmp_path: Path, monkeypatch
) -> None:
    """Failure after mark_stale propagates so caller rolls back and keeps prior showcase."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            PredictionRepository(session).upsert_prediction(
                match_id="old",
                tournament="uel_kz_1",
                market="winner",
                market_spec="winner",
                predictions={"home_win": 0.6, "away_win": 0.4},
                model_version="old-prod",
                algorithm="catboost",
                featureset="basic",
            )

        bundle = tmp_path / "models" / "uel_kz_1" / "winner" / "best"
        bundle.mkdir(parents=True)
        (bundle / "deploy.yaml").write_text(
            "model:\n  algorithm: catboost\n  featureset: basic\n", encoding="utf-8"
        )
        processed = tmp_path / "data" / "processed" / "uel_kz_1"
        processed.mkdir(parents=True)
        pd.DataFrame(
            {
                "id": ["new", "new"],
                "side": ["h", "a"],
                "datetime": ["2026-10-01T12:00:00"] * 2,
                "f1": [1.0, 2.0],
                "odds_raw": [None, None],
            }
        ).to_parquet(processed / "inference_long.parquet", index=False)

        cfg = OmegaConf.create(_build_cfg())
        model_file = bundle / "model_prod.cbm"
        monkeypatch.setattr("sports_forecast.materialize.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "sports_forecast.materialize.find_model_file", lambda *_a, **_k: model_file
        )
        monkeypatch.setattr("sports_forecast.materialize.load_feature_names", lambda _path: ["f1"])
        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.2, 0.8], [0.6, 0.4]])
        monkeypatch.setattr("sports_forecast.materialize.load_model_from_path", lambda *_a: model)

        def fail_after_stale(self, _records):
            previous = self.session.query(Prediction).filter_by(match_id="old").one()
            assert previous.status == "stale"
            raise RuntimeError("simulated bulk upsert failure")

        monkeypatch.setattr(PredictionRepository, "bulk_upsert", fail_after_stale)
        with (
            pytest.raises(RuntimeError, match="simulated bulk upsert failure"),
            get_session(engine=engine) as session,
        ):
            materialize_predictions(cfg, version="prod", session=session)

        with get_session(engine=engine) as session:
            rows = session.query(Prediction).all()
            assert [(row.match_id, row.status) for row in rows] == [("old", "ok")]
    finally:
        reset_engine()
        engine.dispose()


def test_empty_inference_replaces_showcase_with_empty_slice(tmp_path: Path, monkeypatch) -> None:
    """Подтверждённо пустой прогнозный вход убирает старую активную витрину."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            PredictionRepository(session).upsert_prediction(
                match_id="old",
                tournament="uel_kz_1",
                market="winner",
                market_spec="winner",
                predictions={"home_win": 0.6, "away_win": 0.4},
                model_version="old-prod",
                algorithm="catboost",
                featureset="basic",
            )
        interim = tmp_path / "data" / "interim" / "uel_kz_1"
        interim.mkdir(parents=True)
        pd.DataFrame({"id": ["old"]}).to_parquet(interim / "matches_interim.parquet")
        with (
            patch(
                "sports_forecast.features.features_build.materialize_features_config",
                return_value={},
            ),
            patch("sports_forecast.features.features_build.FeaturePipeline") as pipeline,
        ):
            pipeline.return_value.get_generator_summary.return_value = {}
            pipeline.return_value.generate_features.return_value = (
                pd.DataFrame(
                    {"id": ["old", "old"], "side": ["h", "a"], "status": ["finished", "finished"]}
                ),
                [],
            )
            process_tournament_new(
                "uel_kz_1",
                tmp_path / "data" / "interim",
                tmp_path / "data" / "processed",
                OmegaConf.create({"generators": []}),
                inference_only=True,
            )
        monkeypatch.setattr("sports_forecast.materialize.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "sports_forecast.materialize.find_model_file", lambda *_a, **_k: tmp_path / "model"
        )
        monkeypatch.setattr(
            "sports_forecast.materialize.load_model_from_path", lambda *_a: object()
        )
        monkeypatch.setattr("sports_forecast.materialize.load_feature_names", lambda *_a: [])
        with get_session(engine=engine) as session:
            assert materialize_predictions(
                OmegaConf.create(_build_cfg()), version="candidate", session=session
            )
        with get_session(engine=engine) as session:
            assert (
                PredictionRepository(session).count_showcase(
                    tournament="uel_kz_1", market="winner", market_spec="winner"
                )
                == 0
            )
    finally:
        reset_engine()
        engine.dispose()


def test_nonempty_inference_without_both_sides_does_not_clear_showcase(
    tmp_path: Path, monkeypatch
) -> None:
    """Неудачная агрегация непустого входа сохраняет прежние прогнозы."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    try:
        with get_session(engine=engine) as session:
            PredictionRepository(session).upsert_prediction(
                match_id="old",
                tournament="uel_kz_1",
                market="winner",
                market_spec="winner",
                predictions={"home_win": 0.6, "away_win": 0.4},
                model_version="old-prod",
                algorithm="catboost",
                featureset="basic",
            )
        processed = tmp_path / "data" / "processed" / "uel_kz_1"
        processed.mkdir(parents=True)
        pd.DataFrame(
            {
                "id": ["new"],
                "side": ["h"],
                "datetime": ["2026-10-02T12:00:00"],
                "f1": [1.0],
            }
        ).to_parquet(processed / "inference_long.parquet")
        monkeypatch.setattr("sports_forecast.materialize.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "sports_forecast.materialize.find_model_file", lambda *_a, **_k: tmp_path / "model"
        )
        monkeypatch.setattr("sports_forecast.materialize.load_feature_names", lambda *_a: ["f1"])
        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.2, 0.8]])
        monkeypatch.setattr("sports_forecast.materialize.load_model_from_path", lambda *_a: model)
        with (
            pytest.raises(ValueError, match="агрегированных"),
            get_session(engine=engine) as session,
        ):
            materialize_predictions(
                OmegaConf.create(_build_cfg()), version="candidate", session=session
            )
        with get_session(engine=engine) as session:
            assert (
                PredictionRepository(session).count_showcase(
                    tournament="uel_kz_1", market="winner", market_spec="winner"
                )
                == 1
            )
    finally:
        reset_engine()
        engine.dispose()
