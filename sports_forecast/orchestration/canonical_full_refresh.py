"""Full-history rebuild витрины из canonical operational store."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf, open_dict
from sqlalchemy import select

from sports_forecast.config.loaders import (
    load_tournament_config,  # noqa: F401 - публичная точка подмены для теста.
    load_tournament_quality_gate_config,
)
from sports_forecast.data.clean import process_tournament
from sports_forecast.deploy.canonical_bootstrap import refresh_nhl_canonical_from_csv
from sports_forecast.deploy.canonical_snapshot import export_canonical_snapshot
from sports_forecast.deploy.model_bundle import BundleVerificationError, load_current_model_bundle
from sports_forecast.deploy.source_state import export_nhl_source_state
from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.materialize import materialize_predictions
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import CanonicalEvent, CanonicalEventRevision
from sports_forecast.service.db.refresh_lock import RefreshLockRepository
from sports_forecast.service.db.repository import PredictionRepository, WorkerExecutionRepository
from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.canonical_freshness import validate_prediction_result_freshness


logger = get_logger(__name__)


@dataclass(frozen=True)
class FullRefreshResult:
    """Наблюдаемый безопасный outcome одного rebuild run."""

    published: bool
    failure_code: str | None = None
    already_finished: bool = False


def _canonical_rows(tournament: str) -> list[dict[str, Any]]:
    """Загрузить current revision каждого canonical event как provider-shaped row."""
    with get_session() as session:
        rows = session.execute(
            select(CanonicalEvent, CanonicalEventRevision)
            .join(
                CanonicalEventRevision,
                (CanonicalEventRevision.canonical_event_id == CanonicalEvent.id)
                & (
                    CanonicalEventRevision.revision_sha256 == CanonicalEvent.current_revision_sha256
                ),
            )
            .where(CanonicalEvent.tournament == tournament)
        ).all()

    snapshot: list[dict[str, Any]] = []
    for event, revision in rows:
        try:
            payload = json.loads(revision.payload_json)
            result = json.loads(revision.result_json)
        except json.JSONDecodeError as exc:
            raise ValueError("canonical revision содержит невалидный JSON") from exc
        if not isinstance(payload, dict) or not isinstance(result, dict):
            raise ValueError("canonical revision не соответствует payload contract")
        row = dict(payload)
        row.update({key: value for key, value in result.items() if value is not None})
        row["id"] = event.source_event_id
        row["datetime"] = event.scheduled_at.isoformat()
        row["match_is_end"] = "1" if event.status == "finished" else "0"
        snapshot.append(row)
    if not snapshot:
        raise ValueError(f"canonical snapshot пуст для tournament={tournament}")
    return snapshot


def _runtime_cfg(cfg: DictConfig, root: Path, bundle_path: Path) -> DictConfig:
    """Изолировать временные rebuild paths от persistent processed artifacts."""
    runtime_cfg = OmegaConf.create(OmegaConf.to_container(cfg, resolve=True))
    with open_dict(runtime_cfg):
        runtime_cfg.paths.raw_dir = str(root / "raw")
        runtime_cfg.paths.interim_dir = str(root / "interim")
        runtime_cfg.paths.processed_dir = str(root / "processed")
        runtime_cfg.paths.predictions_dir = str(root / "predictions")
        runtime_cfg.runtime_model_bundle = str(bundle_path)
    return runtime_cfg


def _provenance_id(value: object) -> str:
    """Вернуть stable SHA-256 identity без provider payload в logs/DB."""
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _record_publication_state(
    cfg: DictConfig, *, run_id: str, result: FullRefreshResult
) -> FullRefreshResult:
    """Скрыть failed slice либо открыть только успешно materialized витрину."""
    market = str(cfg.market.get("name", cfg.market.get("family", "winner")))
    with get_session() as session:
        PredictionRepository(session).set_publication_state(
            tournament=str(cfg.tournament.name),
            market=market,
            market_spec=str(cfg.market_spec.name),
            status="public" if result.published else "blocked",
            run_id=run_id,
        )
    return result


def run_full_refresh(
    cfg: DictConfig,
    *,
    run_id: str,
    runtime_root: Path,
    app_version: str,
    refreshed_at: datetime,
    source_csv: Path | None = None,
    archive_root: Path | None = None,
) -> FullRefreshResult:
    """Пересобрать NHL features и витрину только из current canonical snapshot.

    ``run_id`` и ``refreshed_at`` входят в публичный контракт job и будут
    использованы execution/freshness lifecycle следующего среза. Здесь rebuild
    намеренно не читает persistent ``processed/inference_*.parquet``.
    """
    tournament = str(cfg.tournament.name)
    with get_session() as session:
        locks = RefreshLockRepository(session)
        executions = WorkerExecutionRepository(session)
        if not locks.acquire(tournament=tournament, run_id=run_id):
            return FullRefreshResult(
                published=False, failure_code="run_locked", already_finished=True
            )
        if not executions.start(run_id):
            locks.release(tournament=tournament, run_id=run_id)
            return FullRefreshResult(published=False, already_finished=True)
    try:
        if source_csv is not None:
            with get_session() as session:
                refresh_nhl_canonical_from_csv(source_csv, session)
        quality_config = load_tournament_quality_gate_config(tournament)
        with get_session() as session:
            freshness = validate_prediction_result_freshness(
                session=session,
                tournament=tournament,
                refreshed_at=refreshed_at,
                match_duration_minutes=quality_config.match_duration_minutes,
                provider_grace_minutes=quality_config.provider_grace_minutes,
            )
        if not freshness.is_valid:
            result = _record_publication_state(
                cfg,
                run_id=run_id,
                result=FullRefreshResult(
                    published=False, failure_code="canonical_freshness_failed"
                ),
            )
            with get_session() as session:
                WorkerExecutionRepository(session).fail(
                    run_id, failure_code="canonical_freshness_failed"
                )
            return result
        bundle = load_current_model_bundle(runtime_root, app_version=app_version)
        snapshot = _canonical_rows(tournament)
        with tempfile.TemporaryDirectory(prefix=f"canonical-refresh-{tournament}-") as directory:
            root = Path(directory)
            runtime_cfg = _runtime_cfg(cfg, root, bundle.path)
            with open_dict(runtime_cfg):
                runtime_cfg.refresh_run_id = run_id
                runtime_cfg.canonical_snapshot_id = _provenance_id(snapshot)
                runtime_cfg.feature_contract_id = _provenance_id(runtime_cfg.features)
            raw_dir = root / "raw" / tournament
            raw_dir.mkdir(parents=True)
            pd.DataFrame(snapshot).to_parquet(raw_dir / "matches.parquet", index=False)

            paths_cfg = OmegaConf.create(
                {
                    "paths": {
                        "interim_dir": str(root / "interim"),
                    }
                }
            )
            # ``cfg`` уже собран Hydra CLI; повторный compose здесь конфликтует
            # с GlobalHydra и делает scheduler run неработоспособным.
            tournament_cfg = runtime_cfg.tournament
            process_tournament(raw_dir, tournament_cfg, paths_cfg)
            process_tournament_new(
                tournament,
                root / "interim",
                root / "processed",
                runtime_cfg.features,
                tournament_cfg,
            )
            with get_session() as session:
                published = materialize_predictions(runtime_cfg, version="prod", session=session)
                result = FullRefreshResult(
                    published=published,
                    failure_code=None if published else "materialization_failed",
                )
                market = str(cfg.market.get("name", cfg.market.get("family", "winner")))
                repository = PredictionRepository(session)
                repository.set_publication_state(
                    tournament=tournament,
                    market=market,
                    market_spec=str(cfg.market_spec.name),
                    status="public" if published else "blocked",
                    run_id=run_id,
                )
                execution = WorkerExecutionRepository(session)
                if published:
                    execution.succeed(
                        run_id,
                        predictions_count=repository.count_showcase(
                            tournament=tournament,
                            market=market,
                            market_spec=str(cfg.market_spec.name),
                        ),
                    )
                else:
                    execution.fail(run_id, failure_code="materialization_failed")
        if published and archive_root is not None:
            with get_session() as session:
                export_canonical_snapshot(
                    session,
                    tournament=tournament,
                    archive_root=archive_root,
                    run_id=run_id,
                    config_id=_provenance_id(cfg),
                    source="nhl_web_api",
                )
            if source_csv is not None:
                export_nhl_source_state(source_csv, archive_root, run_id=run_id)
        return result
    except BundleVerificationError:
        logger.exception("Full refresh отклонён: immutable model bundle не прошёл проверку")
        result = _record_publication_state(
            cfg,
            run_id=run_id,
            result=FullRefreshResult(published=False, failure_code="bundle_verification_failed"),
        )
        with get_session() as session:
            WorkerExecutionRepository(session).fail(
                run_id, failure_code=result.failure_code or "refresh_failed"
            )
        return result
    except (OSError, ValueError):
        logger.exception("Full refresh не выполнил canonical rebuild")
        result = _record_publication_state(
            cfg,
            run_id=run_id,
            result=FullRefreshResult(published=False, failure_code="canonical_rebuild_failed"),
        )
        with get_session() as session:
            WorkerExecutionRepository(session).fail(
                run_id, failure_code=result.failure_code or "refresh_failed"
            )
        return result
    finally:
        with get_session() as session:
            RefreshLockRepository(session).release(tournament=tournament, run_id=run_id)
