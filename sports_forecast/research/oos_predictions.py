"""Общий контракт воспроизводимых помесячных OOS прогнозов для NHL research."""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from omegaconf import OmegaConf
from sklearn.exceptions import ConvergenceWarning

from sports_forecast.identity.snapshot import RegistrySnapshotReader, verify_registry_snapshot
from sports_forecast.research.nhl_universe import _read_matches
from sports_forecast.research.nhl_universe import _sha256 as _sha256_file
from sports_forecast.research.provider_dataset import (
    _expected_nhl_partition,
    _historical_fingerprint,
)
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.training.walk_forward.runner import WalkForwardRunner
from sports_forecast.training.walk_forward.slicer import WalkForwardSlicer
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_FORMAT = "sports-forecast-oos-predictions"
_FORMAT_VERSION = 1
_FEATURE_VERSION = "nhl-weekday-hour-confirmed-teams-v1"
_MODEL_CONFIG = {
    "solver": "saga",
    "penalty": "l2",
    "C": 1.0,
    "max_iter": 1000,
    "random_state": 777,
    "verbose": 0,
    "n_jobs": 1,
}
_TRAINING_START = pd.Timestamp("2017-10-01T00:00:00Z")
_TEAM_VOCAB_CUTOFF = pd.Timestamp("2024-09-24T00:00:00Z")
_REQUIRED_COLUMNS = {
    "project_event_id",
    "source_event_id",
    "kickoff_utc",
    "home_team",
    "away_team",
    "status",
    "home_score_ft",
    "away_score_ft",
    "dataset_eligible",
}
_OPTIONAL_COLUMNS = {"team_identity_eligible"}
_REQUIRED_FINGERPRINTS = {
    "matches_sha256",
    "team_seed_sha256",
    "universe_sha256",
    "provider_dataset_sha256",
    "provider_events_sha256",
}


@dataclass(frozen=True)
class OOSPredictionResult:
    """Канонические прогнозы и manifest одного OOS запуска."""

    predictions: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _utc(value: Any, field: str) -> pd.Timestamp:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        raise ValueError(f"Некорректное UTC значение {field}")
    return pd.Timestamp(stamp)


def _iso(value: pd.Timestamp) -> str:
    return value.tz_convert("UTC").isoformat(timespec="seconds").replace("+00:00", "Z")


def _event_features(row: pd.Series) -> dict[str, Any]:
    kickoff = row["_kickoff"]
    return {
        "weekday_utc": int(kickoff.dayofweek),
        "hour_utc": int(kickoff.hour),
        "home_team": str(row["home_team"]),
        "away_team": str(row["away_team"]),
    }


def _model_features(rows: list[pd.Series], team_vocabulary: tuple[str, ...]) -> pd.DataFrame:
    records = []
    for row in rows:
        event = _event_features(row)
        record: dict[str, float] = {
            "weekday_utc": float(event["weekday_utc"]),
            "hour_utc": float(event["hour_utc"]),
        }
        for team in team_vocabulary:
            record[f"home_team_{team}"] = float(event["home_team"] == team)
            record[f"away_team_{team}"] = float(event["away_team"] == team)
        records.append(record)
    return pd.DataFrame.from_records(records)


def _winner_with_ot_target(row: pd.Series) -> int | None:
    """Вернуть home_win только для завершённого, однозначного полного счёта."""
    if str(row["status"]).strip().casefold() != "finished":
        return None
    home_score = pd.to_numeric(pd.Series([row["home_score_ft"]]), errors="coerce").iloc[0]
    away_score = pd.to_numeric(pd.Series([row["away_score_ft"]]), errors="coerce").iloc[0]
    scores = (home_score, away_score)
    if (
        any(
            pd.isna(score) or not np.isfinite(score) or score < 0 or not float(score).is_integer()
            for score in scores
        )
        or home_score == away_score
    ):
        return None
    return int(home_score > away_score)


def _read_raw_rows_before_cutoff(matches_path: Path, end: str) -> pd.DataFrame:
    """Пушить cutoff в parquet scanner до проекции outcome/status колонок."""
    import pyarrow.dataset as ds

    upper = _utc(end, "end")
    identity = pd.read_parquet(
        matches_path,
        columns=[
            "id",
            "nhl_id",
            "datetime",
            "home_team",
            "away_team",
            "game_type",
        ],
    )
    identity["datetime"] = pd.to_datetime(identity["datetime"], utc=True, errors="coerce")
    identity = identity.loc[
        (identity["datetime"] >= _TRAINING_START) & (identity["datetime"] < upper)
    ].copy()
    scanner = ds.dataset(matches_path, format="parquet")
    date_filter = (ds.field("datetime") >= _iso(_TRAINING_START)) & (
        ds.field("datetime") < _iso(upper)
    )
    outcomes = scanner.to_table(
        columns=["id", "match_is_end", "home_score_ft", "away_score_ft"],
        filter=date_filter,
    ).to_pandas()
    identity_ids = identity["id"].astype(str).tolist()
    outcome_ids = outcomes["id"].astype(str).tolist()
    if len(identity_ids) != len(set(identity_ids)) or len(outcome_ids) != len(set(outcome_ids)):
        raise ValueError("Identity and outcome projection IDs must be unique for one-to-one join")
    if set(outcome_ids) - set(identity_ids):
        raise ValueError("Filtered parquet projection returned rows outside the date cutoff")
    if set(outcome_ids) != set(identity_ids):
        raise ValueError("Filtered outcome projection must exactly cover identity rows")
    merged = identity.merge(outcomes, on="id", how="left", validate="one_to_one", sort=False)
    if len(merged) != len(identity):
        raise ValueError("Filtered outcome projection does not cover development identities")
    return merged


def _universe_rows_by_source(
    universe: dict[str, Any],
    expected: list[tuple[tuple[str, str, str], str | None]],
) -> dict[str, dict[str, Any]]:
    """Проверить resolved rows и timed diagnostics, сохраняя null UUID исключения."""
    resolved = universe.get("nhl_events", [])
    rows = [*resolved, *universe.get("nhl_diagnostics", [])]
    source_map: dict[str, dict[str, Any]] = {}
    key_map: dict[tuple[str, str, str], str | None] = {}
    for row in rows:
        if row.get("kickoff_utc") is None:
            continue
        source_id = str(row.get("source_event_id") or "")
        if not source_id or source_id in source_map:
            raise ValueError("Universe source IDs must be present and unique across timed rows")
        is_resolved = row.get("status") == "resolved"
        if is_resolved and not row.get("project_event_id"):
            raise ValueError("Resolved universe rows must have project UUID")
        if not is_resolved and (
            row.get("status") not in {"unresolved", "conflict"}
            or row.get("project_event_id") is not None
        ):
            continue
        key = (str(row.get("row_id") or ""), source_id, str(row["kickoff_utc"]))
        if key in key_map:
            raise ValueError("Duplicate timed universe identity")
        key_map[key] = row.get("project_event_id")
        source_map[source_id] = row
    if key_map != dict(expected):
        raise ValueError("Universe events and timed diagnostics differ from raw/ir1 partition")
    return source_map


def _universe_projection_for_window(
    universe: dict[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    """Спроецировать full ir1 universe на окно provider dataset с half-open границами."""
    window = universe.get("window", {})
    universe_start = _utc(window.get("start_utc"), "universe.window.start_utc")
    universe_end = _utc(window.get("end_utc_exclusive"), "universe.window.end_utc_exclusive")
    lower, upper = _utc(start, "pd1.window.start_utc"), _utc(end, "pd1.window.end_utc_exclusive")
    if lower >= upper or lower < universe_start or upper > universe_end:
        raise ValueError("Окно pd1 должно быть непустым подмножеством окна pinned ir1 universe")

    def in_window(row: dict[str, Any]) -> bool:
        kickoff = row.get("kickoff_utc")
        if kickoff is None:
            return False
        stamp = _utc(kickoff, "universe.kickoff_utc")
        return lower <= stamp < upper

    return {
        **universe,
        "nhl_events": [row for row in universe.get("nhl_events", []) if in_window(row)],
        "nhl_diagnostics": [row for row in universe.get("nhl_diagnostics", []) if in_window(row)],
    }


def _validate_identity(events: pd.DataFrame) -> None:
    for key in ("project_event_id", "source_event_id"):
        values = events[key].dropna().astype(str).str.strip()
        values = values[values.ne("")]
        if values.duplicated().any():
            raise ValueError(f"duplicate {key}; exact identity is required")
    project_events = events[events["project_event_id"].notna()]
    if project_events["project_event_id"].astype(str).duplicated().any():
        raise ValueError("duplicate project_event_id; reverse mapping must be one-to-one")
    for _, row in events.iterrows():
        if not bool(row["team_identity_eligible"]):
            continue
        home, away = str(row["home_team"]).strip(), str(row["away_team"]).strip()
        if not home or not away or home == away:
            raise ValueError("invalid home/away identity")


def build_oos_predictions(
    events: pd.DataFrame,
    *,
    dataset_id: str,
    registry_snapshot_id: str,
    source_fingerprints: dict[str, str],
    confirmed_team_codes: set[str],
    start: str | datetime,
    end: str | datetime,
) -> OOSPredictionResult:
    """Вычислить одинаковый OOS набор для baseline и logreg без оценки test labels.

    ``events`` содержит только проверенные поля NHL source и провайдера; признаки
    строятся внутри модуля по закреплённому allowlist. Training label допускается
    к fit, только если finished и ``kickoff + 7 дней <= month_start``; это равно
    ограничению ``kickoff <= month_start - 7 дней``.
    """
    unexpected = set(events.columns) - _REQUIRED_COLUMNS - _OPTIONAL_COLUMNS
    missing = _REQUIRED_COLUMNS - set(events.columns)
    if missing or unexpected:
        raise ValueError(
            f"invalid input columns: missing={sorted(missing)}, unexpected columns={sorted(unexpected)}"
        )
    if (
        not dataset_id.startswith("pd1:")
        or len(dataset_id) != 68
        or not registry_snapshot_id.startswith("ir1:")
    ):
        raise ValueError("Требуются закреплённые pd1 dataset и ir1 registry IDs")
    if not _REQUIRED_FINGERPRINTS.issubset(source_fingerprints):
        missing_fingerprints = sorted(_REQUIRED_FINGERPRINTS - set(source_fingerprints))
        raise ValueError(f"Отсутствуют обязательные source fingerprints: {missing_fingerprints}")
    if any(
        not str(value).startswith("sha256:") or len(str(value)) != 71
        for value in source_fingerprints.values()
    ):
        raise ValueError("Все source fingerprints должны быть sha256")
    if not events["dataset_eligible"].map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("dataset_eligible должен содержать только boolean values")
    confirmed = {str(team).strip() for team in confirmed_team_codes if str(team).strip()}
    if not confirmed:
        raise ValueError("Пустой список подтверждённых NHL team codes")

    frame = events.copy().reset_index(drop=True)
    if "team_identity_eligible" not in frame:
        frame["team_identity_eligible"] = True
    else:
        frame["team_identity_eligible"] = frame["team_identity_eligible"].fillna(True)
    if (
        not frame["team_identity_eligible"]
        .map(lambda value: isinstance(value, (bool, np.bool_)))
        .all()
    ):
        raise ValueError("team_identity_eligible must contain only boolean values")
    frame["_kickoff"] = frame["kickoff_utc"].map(lambda value: _utc(value, "kickoff_utc"))
    frame = frame.sort_values(["_kickoff", "source_event_id"], kind="stable").reset_index(drop=True)
    _validate_identity(frame)
    lower, upper = _utc(start, "start"), _utc(end, "end")
    if lower >= upper:
        raise ValueError("OOS interval must satisfy start < end")
    if lower < pd.Timestamp("2023-10-01T00:00:00Z") or upper > pd.Timestamp("2026-05-01T00:00:00Z"):
        raise ValueError("OOS output is limited to development and the locked protocol window")

    for _, row in frame.loc[frame["team_identity_eligible"]].iterrows():
        if (
            str(row["home_team"]).strip() not in confirmed
            or str(row["away_team"]).strip() not in confirmed
        ):
            raise ValueError("team code does not resolve through pinned NHL seed/ir1")
    oos_window = (frame["_kickoff"] >= lower) & (frame["_kickoff"] < upper)
    resolved_oos = oos_window & frame["project_event_id"].notna()
    priced_oos = resolved_oos & frame["dataset_eligible"]
    if not bool(priced_oos.any()):
        raise ValueError("Нет разрешённых OOS событий в заданном окне")

    # Team one-hot vocabulary is fixed before the locked period and never learns from test.
    vocabulary_rows = frame[
        (frame["_kickoff"] >= _TRAINING_START)
        & (frame["_kickoff"] <= _TEAM_VOCAB_CUTOFF)
        & frame["team_identity_eligible"]
    ]
    team_vocabulary = tuple(
        sorted(
            {
                str(team)
                for _, row in vocabulary_rows.iterrows()
                for team in (row["home_team"], row["away_team"])
                if str(team) in confirmed
            }
        )
    )
    if not team_vocabulary:
        raise ValueError("Не удалось построить фиксированный team one-hot vocabulary")

    # Candidate проходит через общий runner; две маски задают proxy-доступность
    # target и исключают строки с непроверяемым score/status из train.
    frame["_slicer_time"] = frame["_kickoff"].dt.tz_localize(None)
    frame["_label_available_at"] = frame["_kickoff"] + pd.Timedelta(days=7)
    targets = frame.apply(_winner_with_ot_target, axis=1)
    frame["_train_eligible"] = (
        targets.notna() & (frame["_kickoff"] >= _TRAINING_START) & frame["team_identity_eligible"]
    )
    y = targets.fillna(0).astype(int)
    feature_rows = [row for _, row in frame.iterrows()]
    features = _model_features(feature_rows, team_vocabulary)
    init_end = pd.Timestamp(lower.tz_convert("UTC").tz_localize(None)) - pd.Timedelta(nanoseconds=1)
    runner_cfg = OmegaConf.create(
        {
            "walk_forward": {"frequency": "month", "reuse_optuna_params": False},
            "betting": {"enabled": False},
            "bookmaker": {},
            "features": {"requires_long": False},
            "market_spec": {},
        }
    )
    runner = WalkForwardRunner(
        runner_cfg,
        lambda _params: LogRegModel(name="epic030-logreg", params=_MODEL_CONFIG),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            walk_forward = runner.run(
                combined_df=frame,
                features=features,
                target=y,
                feature_names=list(features.columns),
                best_params=None,
                init_train_end=init_end,
                time_col="_slicer_time",
                artifact_dir=Path.cwd(),
                label_available_at_col="_label_available_at",
                train_eligible_col="_train_eligible",
                prediction_only=True,
            )
        except ConvergenceWarning as exc:
            raise ValueError("LogReg convergence warning during OOS walk-forward") from exc
    walk_forward_by_month = {
        int(step): (train, test)
        for step, train, test in WalkForwardSlicer(
            frame,
            "_slicer_time",
            "month",
            init_end,
            label_available_at_col="_label_available_at",
            train_eligible_col="_train_eligible",
        )
    }
    month_starts = list(
        pd.date_range(lower.floor("D").replace(day=1), upper, freq="MS", inclusive="left", tz="UTC")
    )
    month_starts = [month for month in month_starts if lower <= month < upper]
    predictions: list[dict[str, Any]] = []
    exclusion_ids: dict[str, set[str]] = {
        "not_finished": set(),
        "invalid_target": set(),
        "unconfirmed_team_identity": set(),
    }
    exclusion_ids["unconfirmed_team_identity"].update(
        frame.loc[~frame["team_identity_eligible"], "source_event_id"].astype(str)
    )
    train_rows_by_month: dict[str, int] = {}
    oos_events_by_month: dict[str, int] = {}
    training_steps: list[dict[str, Any]] = []
    runner_predictions = walk_forward.cumulative_test_df.set_index("row_index")
    for month_start in month_starts:
        kickoff_cutoff = month_start - pd.Timedelta(days=7)
        month_test = (
            (frame["_kickoff"].dt.year == month_start.year)
            & (frame["_kickoff"].dt.month == month_start.month)
        ).to_numpy()
        matching_slice = next(
            (
                pair
                for pair in walk_forward_by_month.values()
                if np.array_equal(pair[1], month_test)
            ),
            None,
        )
        if matching_slice is None:
            continue
        base_train = matching_slice[0]
        eligible = [idx for idx, selected in enumerate(base_train) if bool(selected)]
        labels = [int(targets.iloc[idx]) for idx in eligible]
        training_audit_mask = (
            (frame["_kickoff"] >= _TRAINING_START).to_numpy()
            & (frame["_kickoff"] <= kickoff_cutoff).to_numpy()
            & ~frame["_train_eligible"].to_numpy()
        )
        for idx, is_excluded in enumerate(training_audit_mask):
            if not bool(is_excluded):
                continue
            row = frame.iloc[int(idx)]
            reason = (
                "not_finished"
                if str(row["status"]).strip().casefold() != "finished"
                else "invalid_target"
            )
            exclusion_ids[reason].add(str(row["source_event_id"]))
        if len(set(labels)) < 2:
            raise ValueError(f"Недостаточно двух классов в training rows до {_iso(kickoff_cutoff)}")
        baseline_home = float((sum(labels) + 1) / (len(labels) + 2))
        train_rows_by_month[_iso(month_start)] = len(eligible)
        test_rows = [
            row
            for _, row in frame.loc[month_test].iterrows()
            if lower <= row["_kickoff"] < upper
            and bool(row["dataset_eligible"])
            and bool(row["team_identity_eligible"])
            and pd.notna(row["project_event_id"])
        ]
        train_ids = [str(frame.iloc[idx]["source_event_id"]) for idx in eligible]
        train_ids_hash = _sha256(_canonical_bytes(train_ids))
        training_steps.append(
            {
                "month_start_utc": _iso(month_start),
                "label_availability_cutoff_utc": _iso(month_start),
                "kickoff_cutoff_utc": _iso(kickoff_cutoff),
                "label_availability_proxy": "kickoff_plus_7d",
                "source_ids_sha256": train_ids_hash,
                "train_row_count": len(eligible),
                "train_source_ids": train_ids,
            }
        )
        if not test_rows:
            continue
        oos_events_by_month[_iso(month_start)] = len(test_rows)
        test_indices = [
            idx
            for idx, is_test in enumerate(month_test)
            if bool(is_test) and idx in runner_predictions.index
        ]
        candidate_by_index = runner_predictions.loc[test_indices, "proba_pos"].to_dict()
        month_label = _iso(month_start)
        for row in test_rows:
            p_home = candidate_by_index[int(str(row.name))]
            event_features = _event_features(row)
            encoded_features = _model_features([row], team_vocabulary).iloc[0].to_dict()
            feature_hash = _sha256(
                _canonical_bytes({"feature_version": _FEATURE_VERSION, **encoded_features})
            )
            kickoff = row["_kickoff"]
            common = {
                "dataset_id": dataset_id,
                "registry_snapshot_id": registry_snapshot_id,
                "project_event_id": str(row["project_event_id"]),
                "source_event_id": str(row["source_event_id"]),
                "kickoff_utc": _iso(kickoff),
                "decision_at": _iso(kickoff - pd.Timedelta(minutes=15)),
                "market": "winner_withOT",
                "market_rules": {
                    "outcomes": ["home_win", "away_win"],
                    "overtime": True,
                    "shootout": True,
                    "draw": False,
                },
                "month_start_utc": month_label,
                "training_cutoff_utc": _iso(month_start),
                "kickoff_cutoff_utc": _iso(kickoff_cutoff),
                "label_availability_proxy": "kickoff_plus_7d",
                "oos_basis": "monthly_walk_forward",
                "train_source_ids_sha256": train_ids_hash,
                "train_row_count": len(eligible),
                "training_step_id": month_label,
                "features": event_features,
                "feature_values": {key: float(value) for key, value in encoded_features.items()},
                "feature_hash": feature_hash,
            }
            for name, p in (("candidate", float(p_home)), ("baseline", baseline_home)):
                model_id = _sha256(
                    _canonical_bytes(
                        {
                            "name": name,
                            "config": _MODEL_CONFIG
                            if name == "candidate"
                            else "home_win_frequency_beta_1_1_v1",
                            "training_cutoff_utc": _iso(month_start),
                            "train_source_ids_sha256": train_ids_hash,
                        }
                    )
                )
                predictions.append(
                    {
                        **common,
                        "model_id": model_id,
                        "model_name": name,
                        "config_id": _sha256(
                            _canonical_bytes(
                                {
                                    "feature_version": _FEATURE_VERSION,
                                    "model": name,
                                    "model_config": _MODEL_CONFIG
                                    if name == "candidate"
                                    else "home_win_frequency_beta_1_1_v1",
                                }
                            )
                        ),
                        "probabilities": {"home_win": float(p), "away_win": float(1.0 - p)},
                    }
                )

    event_ids = [row["project_event_id"] for row in predictions if row["model_name"] == "candidate"]
    if not predictions or len(event_ids) != len(set(event_ids)):
        raise ValueError("OOS prediction set must have exactly one row per model/event")
    candidate_ids = {
        row["project_event_id"] for row in predictions if row["model_name"] == "candidate"
    }
    baseline_ids = {
        row["project_event_id"] for row in predictions if row["model_name"] == "baseline"
    }
    if candidate_ids != baseline_ids:
        raise ValueError("candidate and baseline event sets differ")
    prediction_content = b"".join(_canonical_bytes(row) + b"\n" for row in predictions)
    core = {
        "format": _FORMAT,
        "format_version": _FORMAT_VERSION,
        "prediction_id": "op1:" + hashlib.sha256(prediction_content).hexdigest(),
        "dataset_id": dataset_id,
        "registry_snapshot_id": registry_snapshot_id,
        "source_fingerprints": dict(sorted(source_fingerprints.items())),
        "market_rules": {
            "market": "winner_withOT",
            "outcomes": ["home_win", "away_win"],
            "overtime": True,
            "shootout": True,
            "draw": False,
        },
        "feature_allowlist": ["weekday_utc", "hour_utc", "home_team_one_hot", "away_team_one_hot"],
        "feature_version": _FEATURE_VERSION,
        "model_config": _MODEL_CONFIG,
        "team_feature_vocabulary": list(team_vocabulary),
        "training_window_start_utc": _iso(_TRAINING_START),
        "team_vocabulary_cutoff_utc": _iso(_TEAM_VOCAB_CUTOFF),
        "window": {"start_utc": _iso(lower), "end_utc_exclusive": _iso(upper)},
        "expected_oos_events": len(candidate_ids),
        "resolved_oos_events": int(resolved_oos.sum()),
        "resolved_without_usable_price": int((resolved_oos & ~frame["dataset_eligible"]).sum()),
        "unresolved_oos_rows": int((oos_window & frame["project_event_id"].isna()).sum()),
        "oos_events_by_month": oos_events_by_month,
        "training_rows_by_month": train_rows_by_month,
        "training_steps": training_steps,
        "predictions_sha256": _sha256(prediction_content),
        "exclusions": {key: len(values) for key, values in sorted(exclusion_ids.items())},
        "decision_at_semantics": "kickoff_minus_15m_utc; generated_at is intentionally excluded from the deterministic artifact",
    }
    return OOSPredictionResult(tuple(predictions), core)


def write_oos_predictions(result: OOSPredictionResult, output_dir: Path) -> tuple[Path, Path]:
    """Записать canonical JSONL и manifest без полного provider payload."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / f"{result.manifest['prediction_id'].split(':', 1)[1]}.jsonl"
    manifest_path = (
        output_dir / f"{result.manifest['prediction_id'].split(':', 1)[1]}.manifest.json"
    )
    predictions_bytes = b"".join(_canonical_bytes(row) + b"\n" for row in result.predictions)
    manifest_bytes = _canonical_bytes(result.manifest) + b"\n"
    for path, payload in ((predictions_path, predictions_bytes), (manifest_path, manifest_bytes)):
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Existing OOS prediction artifact differs from canonical result")
        if not path.exists():
            path.write_bytes(payload)
    return predictions_path, manifest_path


def load_verified_input(
    *,
    matches_path: Path,
    team_seed_path: Path,
    universe_path: Path,
    provider_manifest_path: Path,
    snapshot_path: Path,
    historical_database_path: Path,
    end: str,
) -> tuple[pd.DataFrame, dict[str, str], str, str, set[str]]:
    """Прочитать raw события после проверки fingerprints и identity TASK-030-1/2."""
    matches_path, team_seed_path, universe_path = map(
        Path, (matches_path, team_seed_path, universe_path)
    )
    provider_path, history_path = Path(provider_manifest_path), Path(historical_database_path)
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    provider = json.loads(provider_path.read_text(encoding="utf-8"))
    if (
        universe.get("format") != "sports-forecast-pinned-nhl-universe"
        or universe.get("format_version") != 1
    ):
        raise ValueError("Invalid pinned NHL universe manifest")
    if (
        provider.get("format") != "sports-forecast-provider-asof-dataset"
        or provider.get("format_version") != 1
    ):
        raise ValueError("Invalid provider dataset manifest")
    config = provider.get("resolved_config", {})
    if (
        config.get("bookmaker") != "pinnacle"
        or config.get("market") != "winner_withOT"
        or config.get("source") != "the_odds_api"
        or config.get("selection_mode") != "provider_as_of"
    ):
        raise ValueError("Provider dataset does not match NHL/Pinnacle/winner_withOT protocol")
    if universe.get("source_fingerprints", {}).get("matches_sha256") != _sha256_file(matches_path):
        raise ValueError("Raw NHL parquet fingerprint differs from universe")
    if universe.get("source_fingerprints", {}).get("team_seed_sha256") != _sha256_file(
        team_seed_path
    ):
        raise ValueError("NHL team seed fingerprint differs from universe")
    if provider.get("universe_sha256") != _sha256_file(universe_path):
        raise ValueError("Provider dataset references a different universe manifest")
    if provider.get("historical_fingerprint") != _historical_fingerprint(history_path):
        raise ValueError("Historical fingerprint differs from provider dataset")
    events_path = provider_path.parent / "events.jsonl"
    if provider.get("events_sha256") != _sha256_file(events_path):
        raise ValueError("Provider events fingerprint differs from manifest")
    core = {key: value for key, value in provider.items() if key != "dataset_id"}
    if provider.get("dataset_id") != "pd1:" + hashlib.sha256(_canonical_bytes(core)).hexdigest():
        raise ValueError("Provider dataset ID does not match canonical manifest")
    snapshot = verify_registry_snapshot(Path(snapshot_path))
    if snapshot.snapshot_id != provider.get(
        "registry_snapshot_id"
    ) or snapshot.snapshot_id != universe.get("snapshot_id"):
        raise ValueError("Pinned ir1 does not match universe/provider dataset")
    if provider.get("universe_run_id") != universe.get("run_id"):
        raise ValueError("Provider dataset references a different pinned universe run")
    registry = RegistrySnapshotReader(snapshot)
    nhl_tournaments = {
        event.tournament_id
        for event in registry.snapshot.event_snapshot.events
        if event.sport == "ice_hockey"
        and registry.get_entity(event.tournament_id).project_name.casefold() == "nhl"
    }
    if len(nhl_tournaments) != 1:
        raise ValueError("Pinned ir1 must contain exactly one NHL tournament")
    nhl_scope = {"sport": "ice_hockey", "tournament": next(iter(nhl_tournaments))}
    provider_window = config
    pd1_start = provider_window.get("window_start_utc")
    pd1_end = provider_window.get("window_end_utc_exclusive")
    if not pd1_start or not pd1_end:
        raise ValueError("Provider dataset manifest must declare its half-open window")
    raw_identity, _, _ = _read_matches(
        matches_path,
        _utc(pd1_start, "pd1.window_start_utc"),
        _utc(pd1_end, "pd1.window_end_utc_exclusive"),
    )
    expected = _expected_nhl_partition(raw_identity, registry)
    projection = _universe_projection_for_window(
        universe,
        _utc(pd1_start, "pd1.window_start_utc"),
        _utc(pd1_end, "pd1.window_end_utc_exclusive"),
    )
    by_source = _universe_rows_by_source(projection, expected)
    provider_rows: dict[str, dict[str, Any]] = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        source_id = str(item.get("source_event_id") or "")
        if not source_id or source_id in provider_rows:
            raise ValueError("Provider dataset has missing/duplicate source IDs")
        provider_rows[source_id] = item
    if len(provider_rows) != int(provider.get("expected_events", -1)):
        raise ValueError("Provider event count differs from manifest")
    if set(provider_rows) != set(by_source):
        raise ValueError("Provider source IDs do not exactly cover pinned universe")
    for source_id, item in provider_rows.items():
        pinned = by_source[source_id]
        if pd.Timestamp(item["kickoff_utc"]) != pd.Timestamp(pinned["kickoff_utc"]) or item.get(
            "project_event_id"
        ) != pinned.get("project_event_id"):
            raise ValueError("Provider UUID/kickoff differs from raw NHL universe identity")

    raw = _read_raw_rows_before_cutoff(matches_path, end)
    seed = yaml.safe_load(team_seed_path.read_text(encoding="utf-8"))
    confirmed = {str(value) for value in seed.get("nhl_api", {}).values()}
    if not confirmed:
        raise ValueError("NHL seed has no confirmed team codes")
    result_rows = []
    for row in raw.itertuples(index=False):
        if str(row.game_type) not in {"regular", "playoffs"}:
            continue
        kickoff = pd.Timestamp(str(row.datetime)).tz_convert("UTC")
        source_id = str(row.nhl_id or row.id)
        universe_row = by_source.get(source_id)
        event_id = (
            universe_row.get("project_event_id")
            if universe_row and pd.Timestamp(universe_row["kickoff_utc"]) == kickoff
            else None
        )
        provider_row = provider_rows.get(source_id)
        eligible = bool(
            event_id
            and provider_row
            and provider_row.get("project_event_id") == event_id
            and pd.Timestamp(provider_row["kickoff_utc"]) == kickoff
            and provider_row.get("coverage") == "covered"
        )
        team_identity_eligible = True
        for code in (str(row.home_team), str(row.away_team)):
            resolution = registry.resolve_designation(
                source="nhl_api",
                kind="team",
                scope=nhl_scope,
                value_kind="external_id",
                raw_value=code,
                at=_iso(kickoff),
            )
            if code not in confirmed or resolution.status != "resolved":
                if event_id is not None:
                    raise ValueError(
                        f"Resolved universe event has an unconfirmed team code: {code}"
                    )
                team_identity_eligible = False
        result_rows.append(
            {
                "project_event_id": event_id,
                "source_event_id": source_id,
                "kickoff_utc": _iso(kickoff),
                "home_team": str(row.home_team),
                "away_team": str(row.away_team),
                "status": "finished" if str(row.match_is_end).strip() == "1" else "scheduled",
                "home_score_ft": row.home_score_ft,
                "away_score_ft": row.away_score_ft,
                "dataset_eligible": eligible,
                "team_identity_eligible": team_identity_eligible,
            }
        )
    fingerprints = {
        "matches_sha256": _sha256_file(matches_path),
        "team_seed_sha256": _sha256_file(team_seed_path),
        "universe_sha256": _sha256_file(universe_path),
        "provider_dataset_sha256": _sha256_file(provider_path),
        "provider_events_sha256": _sha256_file(events_path),
    }
    return (
        pd.DataFrame(result_rows),
        fingerprints,
        provider["dataset_id"],
        snapshot.snapshot_id,
        confirmed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Построение общего NHL OOS prediction contract")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--team-seed", type=Path, required=True)
    parser.add_argument("--universe-manifest", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--mode", choices=("development", "final"), default="development")
    args = parser.parse_args()
    if args.mode == "development" and _utc(args.end, "end") > pd.Timestamp("2024-10-01T00:00:00Z"):
        raise ValueError(
            "Engineering/development mode is restricted to end <= 2024-10-01T00:00:00Z"
        )
    events, fingerprints, dataset_id, snapshot_id, confirmed_teams = load_verified_input(
        matches_path=args.matches,
        team_seed_path=args.team_seed,
        universe_path=args.universe_manifest,
        provider_manifest_path=args.provider_manifest,
        snapshot_path=args.snapshot,
        historical_database_path=args.historical_database,
        end=args.end,
    )
    result = build_oos_predictions(
        events,
        dataset_id=dataset_id,
        registry_snapshot_id=snapshot_id,
        source_fingerprints=fingerprints,
        confirmed_team_codes=confirmed_teams,
        start=args.start,
        end=args.end,
    )
    prediction_path, manifest_path = write_oos_predictions(result, args.output)
    logger.info("Saved %s OOS events: %s", result.manifest["expected_oos_events"], prediction_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
