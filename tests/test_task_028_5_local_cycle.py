"""Полный локальный цикл managed-моделей на реальном предстоящем NHL матче."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostClassifier
from fastapi.testclient import TestClient
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf, open_dict
from sqlalchemy import create_engine

import sports_forecast.data.clean as clean_module
from sports_forecast.config.loaders import (
    load_paths_config,
    load_source_config,
    load_tournament_config,
)
from sports_forecast.data.providers.nhl.assembler import NhlDataAssembler, load_assembler_config
from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.deploy.managed_model import (
    activate_managed_model,
    rollback_managed_model,
)
from sports_forecast.deploy.model_bundle import (
    BundleVerificationError,
    build_managed_model_bundle,
    verify_model_bundle,
)
from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.service.app import app
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import (
    ModelDeployment,
    Prediction,
    PredictionRevision,
    WorkerExecution,
)
from sports_forecast.service.db.repository import PredictionRepository
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.worker import run_worker


APP_VERSION = "1.2.15"
MODEL_POOL = "nhl_winner_with_ot"
MARKET_SPEC = "winner_withOT"
EVENT_ID = "2026020084"
APPROVED_V1_BUNDLE_ID = "sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a"
APPROVED_CATBOOST_SHA256 = "4042e85367a9d3c493a15ef45d0d9dcba9c78004833761224e379c360b0b5cda"


def _load_adapter_model(repo_root: Path, path: Path, algorithm: str) -> object:
    from sports_forecast.predict import load_model_from_path

    algorithm_cfg = OmegaConf.load(repo_root / "conf" / "algorithm" / f"{algorithm}.yaml")
    return load_model_from_path(algorithm_cfg, path)


def test_lgbm_adapter_can_predict_after_save_and_reload(tmp_path: Path) -> None:
    """Сохранённая LightGBM модель остаётся fitted через production adapter."""
    features = pd.DataFrame(
        {"f_home": np.arange(40, dtype=float), "f_away": np.arange(39, -1, -1, dtype=float)}
    )
    labels = pd.Series([0, 1] * 20)
    trained = LGBMModel(
        name="lgbm",
        params={"n_estimators": 5, "n_jobs": 1, "min_child_samples": 2},
    )
    trained.fit(features, labels)
    model_dir = tmp_path / "lgbm_advanced"
    trained.save(model_dir, version="prod")

    loaded = LGBMModel(name="lgbm", params={"n_estimators": 5, "n_jobs": 1})
    loaded.load(model_dir / "lgbm_advanced_prod.txt")
    probabilities = loaded.predict_proba(features.iloc[:2])
    assert probabilities.shape == (2, 2)
    assert np.isfinite(probabilities).all()
    assert np.allclose(probabilities.sum(axis=1), 1.0)


@pytest.mark.integration
def test_real_future_nhl_two_algorithm_worker_database_api_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CatBoost→LightGBM→rollback публикует три immutable revisions в PostgreSQL."""
    database_url = os.environ.get("SF_TASK_028_5_DATABASE_URL")
    if not database_url:
        pytest.skip("Нужна disposable PostgreSQL с применённой Alembic head revision")
    repo_root = Path(__file__).resolve().parents[1]
    approved_bundle_path = Path(
        os.environ.get(
            "SF_TASK_028_5_APPROVED_BUNDLE",
            "/home/xieveer/Документы/codex_projects/operations-agent/tmp/"
            "v1.2.12-model-stage/bundles/"
            "sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a",
        )
    )
    source_csv = Path(
        os.environ.get(
            "SF_TASK_028_5_SOURCE_CSV",
            str(repo_root.parent / "data/source/nhl/source.csv"),
        )
    )
    train_long_path = Path(
        os.environ.get(
            "SF_TASK_028_5_TRAIN_LONG_PARQUET",
            str(repo_root.parent / "data/processed/nhl/train_long.parquet"),
        )
    )
    assert source_csv.is_file()
    assert train_long_path.is_file()

    # Исходный legacy manifest не меняется и проверяется со своей версией.
    original_manifest = json.loads((approved_bundle_path / "manifest.json").read_text())
    verified_v1 = verify_model_bundle(approved_bundle_path, app_version="1.2.12")
    assert verified_v1.bundle_id == APPROVED_V1_BUNDLE_ID
    assert original_manifest["app_version"] == "1.2.12"
    catboost_path = approved_bundle_path / "catboost_advanced_prod.cbm"
    assert hashlib.sha256(catboost_path.read_bytes()).hexdigest() == APPROVED_CATBOOST_SHA256

    with initialize_config_dir(config_dir=str(repo_root / "conf"), version_base="1.3"):
        cfg = compose(
            config_name="config",
            overrides=[
                "tournament=nhl",
                "market=winner_withOT",
                "market_spec=winner_withOT",
                "features=advanced",
                "algorithm=catboost_reg",
            ],
        )

    processed_root = tmp_path / "data/processed"
    cached_inference = os.environ.get("SF_TASK_028_5_INFERENCE_LONG")
    if cached_inference:
        inference_path = Path(cached_inference)
        retrieved_at = datetime.fromtimestamp(inference_path.stat().st_mtime, tz=UTC)
        local_inference_path = processed_root / "nhl/inference_long.parquet"
        local_inference_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inference_path, local_inference_path)
        inference_path = local_inference_path
    else:
        # Изолированное обновление: source CSV читается, parquet создаются во временном каталоге.
        source = pd.read_csv(source_csv, low_memory=False)
        source_cfg = load_source_config("nhl")
        assembler_cfg = replace(
            load_assembler_config(source_cfg.provider),
            date_from=date(2026, 10, 11),
            date_to=date(2026, 10, 11),
            max_games=0,
            checkpoint_file=None,
            schedule_progress_file=None,
            csv_flush_every=0,
        )
        future = NhlDataAssembler(
            NhlApiClient(source_cfg.provider), assembler_cfg
        ).build_dataframe()
        retrieved_at = datetime.now(UTC)
        assert EVENT_ID in set(future["id"].astype(str))
        assert int(future.loc[future["id"].astype(str) == EVENT_ID, "match_is_end"].iloc[0]) == 0
        source["id"] = source["id"].astype(str)
        future["id"] = future["id"].astype(str)
        for column in set(source.columns) & set(future.columns):
            if pd.api.types.is_numeric_dtype(source[column]):
                future[column] = pd.to_numeric(future[column], errors="coerce")
        combined = pd.concat([source, future], ignore_index=True).drop_duplicates("id", keep="last")

        raw_dir = tmp_path / "data/raw/nhl"
        raw_dir.mkdir(parents=True)
        combined.to_parquet(raw_dir / "matches.parquet", index=False)
        monkeypatch.setattr(clean_module, "PROJECT_ROOT", tmp_path)
        tournament_cfg = load_tournament_config("nhl")
        clean_module.process_tournament(raw_dir, tournament_cfg, load_paths_config())
        process_tournament_new(
            "nhl",
            tmp_path / "data/interim",
            processed_root,
            cfg.features,
            tournament_cfg,
            inference_only=True,
        )
        inference_path = processed_root / "nhl/inference_long.parquet"
    inference = pd.read_parquet(inference_path)
    event_rows = inference.loc[inference["id"].astype(str) == EVENT_ID].copy()
    assert len(event_rows) == 2
    feature_names = (approved_bundle_path / "features.txt").read_text().splitlines()
    assert len(feature_names) == 489
    legacy_model = CatBoostClassifier()
    legacy_model.load_model(str(catboost_path))
    assert list(feature_names) == list(legacy_model.feature_names_)
    assert all(pd.api.types.is_numeric_dtype(event_rows[name]) for name in feature_names)
    features = [{"name": name, "type": "float"} for name in feature_names]
    feature_contract_id = (
        "sha256:" + hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest()
    )
    run_token = uuid4().hex
    run_a1 = f"task0285-{run_token}-catboost-a1"
    run_b = f"task0285-{run_token}-lightgbm-b"
    run_a2 = f"task0285-{run_token}-catboost-a2"
    run_ids = [run_a1, run_b, run_a2]

    # Fixture использует размеченную историю NHL и тот же контракт адаптера.
    training = pd.read_parquet(train_long_path).dropna(subset=["pl_goals_full", "opp_goals_full"])
    training = training.sample(min(2500, len(training)), random_state=42)
    labels = (training["pl_goals_full"] > training["opp_goals_full"]).astype(int)
    assert labels.nunique() == 2
    lgbm_source = tmp_path / "lgbm_advanced"
    lgbm_source.mkdir()
    lgbm = LGBMModel(
        name="lgbm",
        params={"n_estimators": 15, "n_jobs": 1, "min_child_samples": 10},
    )
    lgbm.fit(training[feature_names].apply(pd.to_numeric, errors="coerce"), labels)
    lgbm.save(lgbm_source, version="prod")
    (lgbm_source / "features.txt").write_text("\n".join(feature_names) + "\n")
    (lgbm_source / "deploy.yaml").write_text(
        "model:\n  algorithm: lgbm\n  featureset: advanced\n", encoding="utf-8"
    )

    bundle_root = tmp_path / "runtime/bundles"
    bundle_root.mkdir(parents=True)
    cat_source = tmp_path / "approved-catboost-v2-source"
    cat_source.mkdir()
    for filename in ("catboost_advanced_prod.cbm", "features.txt", "deploy.yaml"):
        shutil.copy2(approved_bundle_path / filename, cat_source / filename)
    (cat_source / "approved_v1_provenance.json").write_text(
        json.dumps(
            {
                "source_bundle_id": APPROVED_V1_BUNDLE_ID,
                "source_app_version": "1.2.12",
                "source_model_sha256": APPROVED_CATBOOST_SHA256,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    def managed_bundle(source_path: Path, identity: str, algorithm: str, entrypoint: str):
        return build_managed_model_bundle(
            source_path,
            bundle_root,
            model_identity=identity,
            app_version=APP_VERSION,
            model_pool=MODEL_POOL,
            market_spec=MARKET_SPEC,
            market_rules={"overtime": True, "shootout": True, "draw": False},
            outcomes=["home_win", "away_win"],
            feature_contract_id=feature_contract_id,
            features=features,
            transformations_version="nhl-advanced-local-cycle-v1",
            algorithm=algorithm,
            model_entrypoint=entrypoint,
        )

    bundle_a = managed_bundle(
        cat_source,
        f"pool:{MODEL_POOL}:{MARKET_SPEC}:approved-catboost-local-v2-{run_token}",
        "catboost_reg",
        "catboost_advanced_prod.cbm",
    )
    bundle_b = managed_bundle(
        lgbm_source,
        f"pool:{MODEL_POOL}:{MARKET_SPEC}:local-lightgbm-fixture-{run_token}",
        "lgbm",
        "lgbm_advanced_prod.txt",
    )
    assert (
        hashlib.sha256((bundle_a.path / "catboost_advanced_prod.cbm").read_bytes()).hexdigest()
        == APPROVED_CATBOOST_SHA256
    )
    evidence = {
        "event_id": EVENT_ID,
        "source_namespace": "nhl_api",
        "schedule_retrieved_at_utc": retrieved_at.isoformat(),
        "inference_parquet_sha256": hashlib.sha256(inference_path.read_bytes()).hexdigest(),
        "approved_source_bundle_id": APPROVED_V1_BUNDLE_ID,
        "approved_catboost_sha256": APPROVED_CATBOOST_SHA256,
        "managed_catboost_bundle_id": bundle_a.bundle_id,
        "managed_lightgbm_bundle_id": bundle_b.bundle_id,
        "feature_count": len(feature_names),
        "event_feature_missing_cells": int(event_rows[feature_names].isna().sum().sum()),
        "lightgbm_training_rows": len(training),
        "catboost_version": package_version("catboost"),
        "lightgbm_version": package_version("lightgbm"),
    }
    (tmp_path / "task0285-evidence.json").write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    engine = create_engine(database_url, pool_size=4)
    from sports_forecast import materialize as materialize_module
    from sports_forecast import worker as worker_module
    from sports_forecast.service.routers import predictions as predictions_router

    def test_session():
        return get_session(engine=engine)

    monkeypatch.setattr(worker_module, "get_session", test_session)
    monkeypatch.setattr(materialize_module, "get_session", test_session)
    monkeypatch.setattr(predictions_router, "get_session", test_session)
    monkeypatch.setattr(predictions_router, "batch_live_response_extras", lambda *_a, **_k: {})
    monkeypatch.setattr(materialize_module, "PROJECT_ROOT", repo_root)
    with open_dict(cfg):
        cfg.paths.processed_dir = str(processed_root)
        cfg.paths.predictions_dir = str(tmp_path / "predictions")
        cfg.model_pool = {"name": MODEL_POOL}
        cfg.source_namespace = "nhl_api"
        cfg.feature_contract_id = feature_contract_id

    def loader(path: Path, algorithm: str) -> object:
        return _load_adapter_model(repo_root, path, algorithm)

    def activate(bundle) -> None:
        with get_session(engine=engine) as session:
            activate_managed_model(
                session,
                bundle_path=bundle.path,
                bundle_root=bundle_root,
                app_version=APP_VERSION,
                model_pool=MODEL_POOL,
                market_spec=MARKET_SPEC,
                candidate_report_ref=f"local-task-028-5/{bundle.bundle_id}.json",
                feature_contract_id=feature_contract_id,
                features=features,
                load_model=loader,
            )

    try:
        activate(bundle_a)
        damaged_source = tmp_path / "damaged-source"
        shutil.copytree(lgbm_source, damaged_source)
        damaged = managed_bundle(
            damaged_source,
            f"pool:{MODEL_POOL}:{MARKET_SPEC}:damaged-candidate-{run_token}",
            "lgbm",
            "lgbm_advanced_prod.txt",
        )
        with (damaged.path / "lgbm_advanced_prod.txt").open("ab") as file:
            file.write(b"tamper")
        with pytest.raises(BundleVerificationError):
            activate(damaged)
        with get_session(engine=engine) as session:
            assert (
                session.query(ModelDeployment)
                .filter_by(model_pool=MODEL_POOL, market_spec=MARKET_SPEC, is_active=True)
                .one()
                .bundle_id
                == bundle_a.bundle_id
            )

        assert run_worker(
            cfg,
            run_id=run_a1,
            runtime_root=bundle_root,
            app_version=APP_VERSION,
        )
        activate(bundle_b)
        assert run_worker(
            cfg,
            run_id=run_b,
            runtime_root=bundle_root,
            app_version=APP_VERSION,
        )
        with get_session(engine=engine) as session:
            rollback_managed_model(
                session,
                model_pool=MODEL_POOL,
                market_spec=MARKET_SPEC,
                model_identity=bundle_a.model_identity,
                bundle_root=bundle_root,
                app_version=APP_VERSION,
                load_model=loader,
            )
        assert run_worker(
            cfg,
            run_id=run_a2,
            runtime_root=bundle_root,
            app_version=APP_VERSION,
        )

        with get_session(engine=engine) as session:
            revisions = [
                revision
                for revision in (
                    session.query(PredictionRevision)
                    .filter_by(source_event_id=EVENT_ID, source_namespace="nhl_api")
                    .order_by(PredictionRevision.created_at)
                    .all()
                )
                if revision.run_id in run_ids
            ]
            assert len(revisions) == 3
            assert {row.run_id for row in revisions} == set(run_ids)
            assert len({row.revision_id for row in revisions}) == 3
            assert [row.bundle_id for row in revisions] == [
                bundle_a.bundle_id,
                bundle_b.bundle_id,
                bundle_a.bundle_id,
            ]
            current = (
                session.query(Prediction)
                .filter_by(match_id=EVENT_ID, source_namespace="nhl_api")
                .one()
            )
            assert current.current_revision_id == revisions[-1].revision_id
            assert PredictionRepository(session).get_revision(revisions[0].revision_id)
            executions = [
                execution
                for execution in session.query(WorkerExecution).all()
                if execution.run_id in run_ids
            ]
            assert {row.run_id for row in executions} == set(run_ids)
            assert {row.status for row in executions} == {"succeeded"}

        # Повтор завершённого Worker run идемпотентен и не создаёт новую revision.
        assert run_worker(cfg, run_id=run_a2, runtime_root=bundle_root, app_version=APP_VERSION)
        with get_session(engine=engine) as session:
            matching_revisions = [
                revision
                for revision in session.query(PredictionRevision).filter_by(
                    source_event_id=EVENT_ID, source_namespace="nhl_api"
                )
                if revision.run_id in run_ids
            ]
            assert len(matching_revisions) == 3

        response = TestClient(app).get(
            "/predict/upcoming/nhl",
            params={
                "market": "winner_withOT",
                "market_spec": MARKET_SPEC,
                "live_pinnacle": "false",
            },
        )
        assert response.status_code == 200
        prediction = next(
            item for item in response.json()["predictions"] if item["match_id"] == EVENT_ID
        )
        assert prediction["predictions"] == json.loads(revisions[-1].probabilities_json)

        class InvalidProbabilityModel:
            def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
                return np.full((len(features), 2), np.nan)

        monkeypatch.setattr(
            materialize_module, "load_model_from_path", lambda *_args: InvalidProbabilityModel()
        )
        invalid_run = f"task0285-{run_token}-invalid-probabilities"
        assert not run_worker(
            cfg,
            run_id=invalid_run,
            runtime_root=bundle_root,
            app_version=APP_VERSION,
        )
        with get_session(engine=engine) as session:
            matching_revisions = [
                revision
                for revision in session.query(PredictionRevision).filter_by(
                    source_event_id=EVENT_ID, source_namespace="nhl_api"
                )
                if revision.run_id in run_ids
            ]
            assert len(matching_revisions) == 3
            assert (
                session.query(Prediction)
                .filter_by(match_id=EVENT_ID, source_namespace="nhl_api")
                .one()
                .current_revision_id
                == revisions[-1].revision_id
            )
            failed_execution = session.query(WorkerExecution).filter_by(run_id=invalid_run).one()
            assert failed_execution.status == "failed"
        evidence.update(
            {
                "revision_count_a_b_a": len(revisions),
                "revision_ids": [row.revision_id for row in revisions],
                "revision_bundle_order": [row.bundle_id for row in revisions],
                "worker_run_ids": run_ids,
                "damaged_candidate_rejected": True,
                "invalid_probability_run_rejected": True,
                "repeated_worker_run_idempotent": True,
                "api_reflects_latest_revision": True,
            }
        )
        (tmp_path / "task0285-evidence.json").write_text(
            json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        engine.dispose()
