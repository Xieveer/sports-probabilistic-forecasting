"""Full-history rebuild витрины из canonical operational store."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from hydra._internal.config_loader_impl import ConfigLoaderImpl
from hydra._internal.utils import create_config_search_path
from hydra.errors import HydraException
from hydra.types import RunMode
from omegaconf import DictConfig, OmegaConf, open_dict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sports_forecast.config.loaders import (
    PROJECT_ROOT,
    load_tournament_config,  # noqa: F401 - публичная точка подмены для теста.
    load_tournament_quality_gate_config,
)
from sports_forecast.data.clean import process_tournament
from sports_forecast.deploy.canonical_bootstrap import (
    refresh_nhl_canonical_with_summary_from_csv,
)
from sports_forecast.deploy.canonical_snapshot import export_canonical_snapshot
from sports_forecast.deploy.model_bundle import BundleVerificationError, load_current_model_bundle
from sports_forecast.deploy.source_state import export_nhl_source_state
from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.materialize import materialize_predictions
from sports_forecast.orchestration.future_odds import run_nhl_future_odds_batch
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import CanonicalEvent, CanonicalEventRevision, Prediction
from sports_forecast.service.db.refresh_lock import RefreshLockRepository
from sports_forecast.service.db.repository import (
    CalendarRepository,
    DataCycleRunRepository,
    PredictionRepository,
    WorkerExecutionRepository,
)
from sports_forecast.service.event_readiness import evaluate_event_readiness
from sports_forecast.service.readiness_policy import load_readiness_policy
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


def _load_bundle_features_config(bundle_path: Path, *, algorithm: str) -> DictConfig:
    """Скомпоновать featureset из проверенного bundle и проверить runtime algorithm."""
    try:
        deploy_config = yaml.safe_load((bundle_path / "deploy.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise BundleVerificationError("promoted model contract is unavailable or invalid") from exc

    model_config = deploy_config.get("model") if isinstance(deploy_config, dict) else None
    deployed_algorithm = model_config.get("algorithm") if isinstance(model_config, dict) else None
    featureset = model_config.get("featureset") if isinstance(model_config, dict) else None
    if (
        not isinstance(deployed_algorithm, str)
        or not deployed_algorithm.strip()
        or deployed_algorithm != algorithm
        or not isinstance(featureset, str)
        or not featureset.strip()
        or Path(featureset).name != featureset
    ):
        raise BundleVerificationError("promoted model contract does not match runtime config")

    config_dir = (PROJECT_ROOT / "conf").resolve()
    config_loader = ConfigLoaderImpl(create_config_search_path(str(config_dir)))
    try:
        composed = config_loader.load_configuration(
            config_name=f"features/{featureset}", overrides=[], run_mode=RunMode.RUN
        )
    except HydraException as exc:
        raise BundleVerificationError(
            "promoted featureset config is unavailable or invalid"
        ) from exc

    features_config = composed.get("features")
    if (
        not isinstance(features_config, DictConfig)
        or features_config.get("name") != featureset
        or not isinstance(features_config.get("generators"), DictConfig)
    ):
        raise BundleVerificationError("promoted featureset config is invalid")
    return features_config


def _provenance_id(value: object) -> str:
    """Вернуть stable SHA-256 identity без provider payload в logs/DB."""
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _assert_run_publication_owner(session: Session, run_id: str) -> None:
    """Проверить fencing под row lock в транзакции DB publication write."""
    cycles = DataCycleRunRepository(session)
    run = cycles.get(run_id)
    if run is None or run.executor_owner_id is None:
        return
    raw_generation = os.environ.get("SF_DATA_CYCLE_GENERATION")
    if raw_generation is None:
        raise RuntimeError("Data Cycle executor generation is required for publication")
    try:
        generation = int(raw_generation)
    except ValueError as exc:
        raise ValueError("Некорректная Data Cycle generation") from exc
    cycles.assert_executor_owner(run_id, owner_generation=generation)


def _record_publication_state(
    cfg: DictConfig, *, run_id: str, result: FullRefreshResult
) -> FullRefreshResult:
    """Скрыть failed slice либо открыть только успешно materialized витрину."""
    market = str(cfg.market.get("name", cfg.market.get("family", "winner")))
    with get_session() as session:
        _assert_run_publication_owner(session, run_id)
        PredictionRepository(session).set_publication_state(
            tournament=str(cfg.tournament.name),
            market=market,
            market_spec=str(cfg.market_spec.name),
            status="public" if result.published else "blocked",
            run_id=run_id,
        )
    return result


def _start_cycle_stage(run_id: str, stage: str) -> bool:
    """Начать Data Cycle stage для scheduler run, сохраняя standalone Worker."""
    with get_session() as session:
        repository = DataCycleRunRepository(session)
        if repository.get(run_id) is None:
            return False
        repository.start_stage(run_id, stage)
    return True


def _finish_cycle_stage(
    run_id: str,
    stage: str,
    *,
    status: str,
    counts: dict[str, int] | None = None,
    failure_code: str | None = None,
) -> None:
    """Закрыть Data Cycle stage, если запуск создан scheduler wrapper-ом."""
    with get_session() as session:
        repository = DataCycleRunRepository(session)
        if repository.get(run_id) is not None:
            repository.finish_stage(
                run_id,
                stage,
                status=status,
                counts=counts,
                failure_code=failure_code,
            )


def _eligible_calendar_events(
    session: Session, *, tournament: str, at: datetime
) -> tuple[list[CanonicalEvent], dict[str, Any]] | None:
    """Select the policy-defined upcoming denominator for one run timestamp."""
    policy = load_readiness_policy(tournament)
    days = policy.get("eligibility_window_days") if policy is not None else None
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        return None
    now = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
    events = session.scalars(
        select(CanonicalEvent)
        .where(
            CanonicalEvent.tournament == tournament,
            CanonicalEvent.scheduled_at >= now.replace(tzinfo=None),
            CanonicalEvent.scheduled_at < (now + timedelta(days=days)).replace(tzinfo=None),
            CanonicalEvent.status == "scheduled",
        )
        .order_by(CanonicalEvent.scheduled_at, CanonicalEvent.source_event_id)
    ).all()
    return events, policy


def _readiness_counts(
    session: Session,
    *,
    tournament: str,
    at: datetime,
) -> dict[str, int]:
    """Count event readiness on one explicit calendar window and timestamp."""
    selected = _eligible_calendar_events(session, tournament=tournament, at=at)
    if selected is None:
        return {}
    events, policy = selected
    predictions, odds, attempts = CalendarRepository(session).get_readiness_data(events)
    counts = {
        "eligible_events": len(events),
        "odds_eligible_events": len(events),
        "predictions_ready": 0,
        "odds_ready": 0,
        "fully_ready_events": 0,
        "partially_ready_events": 0,
        "errors": 0,
    }
    for event in events:
        readiness = evaluate_event_readiness(
            event,
            predictions.get(event.id, []),
            odds.get(event.id, []),
            policy,
            at,
            attempts.get(event.id, []),
        )
        prediction_state = readiness["prediction_readiness"]["status"]
        odds_state = readiness["odds_readiness"]["status"]
        overall_state = readiness["readiness"]["status"]
        counts["predictions_ready"] += int(prediction_state == "ready")
        counts["odds_ready"] += int(odds_state == "ready")
        counts["fully_ready_events"] += int(overall_state == "ready")
        counts["partially_ready_events"] += int(overall_state == "partial")
        counts["errors"] += int(overall_state == "error")
    return counts


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
        cycle = DataCycleRunRepository(session)
        _assert_run_publication_owner(session, run_id)
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
        cycle_present = False
        if source_csv is not None:
            with get_session() as session:
                import_summary = refresh_nhl_canonical_with_summary_from_csv(source_csv, session)
            with get_session() as session:
                cycle = DataCycleRunRepository(session)
                if cycle.get(run_id) is not None:
                    cycle_present = True
                    cycle.finish_stage(
                        run_id,
                        "calendar",
                        status="success",
                        counts={
                            "events": import_summary.events_found,
                            "events_found": import_summary.events_found,
                            "new_events": import_summary.new_events,
                            "changed_events": import_summary.changed_events,
                        },
                    )
        if not cycle_present:
            cycle_present = _start_cycle_stage(run_id, "data_odds")
        else:
            _start_cycle_stage(run_id, "data_odds")
        if cycle_present:
            with get_session() as session:
                attempt = run_nhl_future_odds_batch(
                    session,
                    run_id=run_id,
                    now=refreshed_at,
                )
            stage_status = attempt.status
            if stage_status == "success" and attempt.missing_events > 0:
                stage_status = "partial_success"
            with get_session() as session:
                DataCycleRunRepository(session).finish_stage(
                    run_id,
                    "data_odds",
                    status=stage_status,
                    counts={
                        "canonical_events": attempt.matched_events + attempt.missing_events,
                        "independently_observed_events": attempt.matched_events,
                        "stage_errors": int(attempt.status == "failed"),
                    },
                    failure_code=(
                        "odds_acquisition_failed" if attempt.status == "failed" else None
                    ),
                )
        _start_cycle_stage(run_id, "quality")
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
            _finish_cycle_stage(
                run_id,
                "quality",
                status="failed",
                failure_code="quality_failed",
            )
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
        _finish_cycle_stage(run_id, "quality", status="success")
        _start_cycle_stage(run_id, "predictions")
        bundle = load_current_model_bundle(runtime_root, app_version=app_version)
        features_config = _load_bundle_features_config(
            bundle.path, algorithm=str(cfg.algorithm.name)
        )
        snapshot = _canonical_rows(tournament)
        with tempfile.TemporaryDirectory(prefix=f"canonical-refresh-{tournament}-") as directory:
            root = Path(directory)
            runtime_cfg = _runtime_cfg(cfg, root, bundle.path)
            with open_dict(runtime_cfg):
                runtime_cfg.features = features_config
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
            _finish_cycle_stage(
                run_id,
                "predictions",
                status="success",
                counts={"canonical_events": len(snapshot)},
            )
            _start_cycle_stage(run_id, "publication")
            with get_session() as session:
                _assert_run_publication_owner(session, run_id)
                published = materialize_predictions(runtime_cfg, version="prod", session=session)
                readiness_as_of = datetime.now(UTC)
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
                cycle = DataCycleRunRepository(session)
                cycle_exists = cycle.get(run_id) is not None
                if published:
                    predictions_count = int(
                        session.scalar(
                            select(func.count(Prediction.id)).where(
                                Prediction.tournament == tournament,
                                Prediction.market == market,
                                Prediction.market_spec == str(cfg.market_spec.name),
                                Prediction.refresh_run_id == run_id,
                                Prediction.status == "ok",
                            )
                        )
                        or 0
                    )
                    execution.succeed(run_id, predictions_count=predictions_count)
                    if cycle_exists:
                        publication_counts = {
                            "predictions": predictions_count,
                            **_readiness_counts(session, tournament=tournament, at=readiness_as_of),
                        }
                        cycle.finish_stage(
                            run_id,
                            "publication",
                            status="success",
                            at=readiness_as_of,
                            counts=publication_counts,
                        )
                else:
                    execution.fail(run_id, failure_code="materialization_failed")
                    if cycle_exists:
                        publication_counts = _readiness_counts(
                            session, tournament=tournament, at=readiness_as_of
                        )
                        cycle.finish_stage(
                            run_id,
                            "publication",
                            status="failed",
                            at=readiness_as_of,
                            counts=publication_counts,
                            failure_code="publication_failed",
                        )
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
