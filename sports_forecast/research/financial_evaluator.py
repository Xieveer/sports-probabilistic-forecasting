"""Общий воспроизводимый evaluator вероятностей и ставок."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from sports_forecast.betting.bootstrap import BlockBootstrap
from sports_forecast.betting.simulator import BettingSimulator
from sports_forecast.research import oos_predictions as oos_contract
from sports_forecast.research.nhl_universe import _sha256 as _sha256_file
from sports_forecast.research.oos_predictions import load_verified_input
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_MARKET_RULES = {
    "market": "winner_withOT",
    "outcomes": ["home_win", "away_win"],
    "overtime": True,
    "shootout": True,
    "draw": False,
}


@dataclass(frozen=True)
class FinancialEvaluationConfig:
    """Заранее фиксированные параметры ставки и bootstrap."""

    min_edge: float = 0.05
    flat_stake: float = 10.0
    initial_bankroll: float = 1000.0
    max_stake_fraction: float = 0.10
    n_bootstrap: int = 5000
    min_block_length: int = 10
    max_block_length: int = 30
    seed: int = 777
    min_comparable: int = 200
    min_bets: int = 40
    min_bet_months: int = 4
    min_positive_bootstrap_fraction: float = 0.80
    min_bet_coverage: float = 0.20


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_instant(left: Any, right: Any) -> bool:
    """Сравнить абсолютные UTC-моменты независимо от точности ISO сериализации."""
    first, second = pd.Timestamp(left), pd.Timestamp(right)
    return (
        first.tz is not None
        and second.tz is not None
        and first.tz_convert("UTC") == second.tz_convert("UTC")
    )


def _settled_home_winner(status: Any, home_score: Any, away_score: Any) -> int | None:
    """Вернуть winner_withOT только при завершённом матче с целым неотрицательным счётом."""
    if str(status).strip().casefold() != "finished":
        return None
    scores = (_number(home_score), _number(away_score))
    if any(
        score is None or not np.isfinite(score) or score < 0 or not float(score).is_integer()
        for score in scores
    ):
        raise ValueError("Завершённый матч должен иметь конечные неотрицательные целые голы")
    if scores[0] == scores[1]:
        raise ValueError("Завершённый матч winner_withOT не может иметь равный итоговый счёт")
    return int(scores[0] > scores[1])


def _validate_events(events: pd.DataFrame) -> pd.DataFrame:
    required = {
        "project_event_id",
        "source_event_id",
        "kickoff_utc",
        "decision_at",
        "home_win",
        "home_odds",
        "away_odds",
        "price_age_seconds",
        "candidate_home",
        "candidate_away",
        "baseline_home",
        "baseline_away",
        "coverage",
        "retrieved_at",
    }
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Во входных данных evaluator отсутствуют поля: {sorted(missing)}")
    frame = events.copy()
    for key in ("project_event_id", "source_event_id"):
        values = frame[key].dropna().astype(str)
        if values.empty or values.str.strip().eq("").any() or values.duplicated().any():
            raise ValueError(f"Поле {key} содержит дубликат или пропуск")
    for prefix in ("candidate", "baseline"):
        for _, row in frame.iterrows():
            home, away = _number(row[f"{prefix}_home"]), _number(row[f"{prefix}_away"])
            if home is None and away is None:
                continue
            if home is None or away is None or not np.isfinite([home, away]).all():
                raise ValueError(f"{prefix}: вероятности должны быть конечной парой")
            if not (0 <= home <= 1 and 0 <= away <= 1) or not np.isclose(
                home + away, 1.0, atol=1e-9
            ):
                raise ValueError(
                    f"{prefix}: вероятности двух исходов должны быть в [0, 1] и суммироваться в 1"
                )
    if not frame["candidate_home"].notna().equals(frame["baseline_home"].notna()):
        raise ValueError("candidate и baseline должны иметь одинаковый набор событий")
    for _, row in frame.iterrows():
        target = _number(row["home_win"])
        if target is not None and target not in (0.0, 1.0):
            raise ValueError("Исход winner_withOT должен быть двоичным")
        if str(row["coverage"]) == "covered":
            odds = [_number(row["home_odds"]), _number(row["away_odds"])]
            if any(value is None or not np.isfinite(value) or value <= 1 for value in odds):
                raise ValueError(
                    "Для covered-события нужны два конечных десятичных коэффициента больше 1"
                )
            age = _number(row["price_age_seconds"])
            if age is None or not np.isfinite(age) or not (0 <= age <= 86400):
                raise ValueError(
                    "Для covered-события возраст цены должен быть конечным и в пределах 24 часов"
                )
    frame["_kickoff"] = pd.to_datetime(frame["kickoff_utc"], utc=True, errors="raise")
    decision = pd.to_datetime(frame["decision_at"], utc=True, errors="raise")
    if not (decision == frame["_kickoff"] - pd.Timedelta(minutes=15)).all():
        raise ValueError("decision_at должен равняться kickoff минус 15 минут")
    return frame.sort_values(["_kickoff", "source_event_id"], kind="stable").reset_index(drop=True)


def _ml_metrics(frame: pd.DataFrame, prefix: str) -> dict[str, Any]:
    comparable = frame[
        frame["coverage"].eq("covered")
        & frame["_target"].notna()
        & frame[f"{prefix}_home"].notna()
        & frame[f"{prefix}_away"].notna()
    ]
    if comparable.empty:
        return {"n": 0, "log_loss": None, "brier": None, "calibration": None}
    y = comparable["_target"].to_numpy(dtype=int)
    p = comparable[f"{prefix}_home"].to_numpy(dtype=float)
    bins: list[dict[str, float | int]] = []
    for low in (index / 10 for index in range(10)):
        mask = (p >= low) & (p < low + 0.1 if low < 0.9 else p <= 1)
        if mask.any():
            bins.append(
                {
                    "count": int(mask.sum()),
                    "mean_probability": float(p[mask].mean()),
                    "observed_rate": float(y[mask].mean()),
                }
            )
    return {
        "n": len(comparable),
        "log_loss": float(log_loss(y, np.column_stack([1 - p, p]), labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "calibration": bins,
    }


def _model_trace(
    frame: pd.DataFrame,
    prefix: str,
    config: FinancialEvaluationConfig,
    *,
    max_price_age_seconds: int = 86400,
) -> tuple[dict[str, Any], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    selected_p: list[float] = []
    selected_odds: list[float] = []
    selected_outcome: list[float] = []
    allowed: list[bool] = []
    for _, row in frame.iterrows():
        p_home, p_away = _number(row[f"{prefix}_home"]), _number(row[f"{prefix}_away"])
        home_odds, away_odds = _number(row["home_odds"]), _number(row["away_odds"])
        valid_target = _number(row["_target"])
        price_ok = (
            row["coverage"] == "covered"
            and home_odds is not None
            and away_odds is not None
            and _number(row["price_age_seconds"]) is not None
            and float(row["price_age_seconds"]) <= max_price_age_seconds
        )
        has_prediction = p_home is not None and p_away is not None
        edge_home = p_home - 1 / home_odds if has_prediction and price_ok else None
        edge_away = p_away - 1 / away_odds if has_prediction and price_ok else None
        comparable = bool(price_ok and has_prediction and valid_target is not None)
        side: str | None = None
        no_bet_reason: str | None = None
        if not has_prediction:
            no_bet_reason = "missing_prediction"
        elif row["coverage"] != "covered":
            no_bet_reason = f"price_{row['coverage']}"
        elif not price_ok:
            no_bet_reason = "price_too_old_or_invalid"
        elif valid_target is None:
            no_bet_reason = "invalid_outcome"
        elif np.isclose(edge_home, edge_away, rtol=0.0, atol=1e-12):
            no_bet_reason = "equal_max_edge"
        elif max(edge_home, edge_away) <= config.min_edge:
            no_bet_reason = "edge_below_threshold"
        else:
            side = "home_win" if edge_home > edge_away else "away_win"
        can_place = bool(comparable and side is not None)
        if side == "home_win":
            selected_p.append(float(p_home))
            selected_odds.append(float(home_odds))
            selected_outcome.append(float(valid_target))
        elif side == "away_win":
            selected_p.append(float(p_away))
            selected_odds.append(float(away_odds))
            selected_outcome.append(float(1 - valid_target))
        else:
            selected_p.append(0.5)
            selected_odds.append(2.0)
            selected_outcome.append(float(valid_target or 0))
        allowed.append(can_place)
        rows.append(
            {
                "project_event_id": str(row["project_event_id"]),
                "source_event_id": str(row["source_event_id"]),
                "kickoff_utc": row["_kickoff"].isoformat().replace("+00:00", "Z"),
                "decision_at": row["decision_at"],
                "ho1": row.get("observation_id"),
                "ir1": row.get("registry_snapshot_id"),
                "receipt_id": row.get("receipt_id"),
                "source_file_sha256": row.get("source_file_sha256"),
                "model_name": prefix,
                "model_id": row.get(f"{prefix}_model_id"),
                "config_id": row.get(f"{prefix}_config_id"),
                "retrieved_at": row.get("retrieved_at"),
                "observed_at": row.get("observed_at"),
                "retrieval_status": row.get("retrieval_status"),
                "late_retrieval": row.get("late_retrieval"),
                "selected_side": side,
                "probabilities": {"home_win": p_home, "away_win": p_away},
                "prices": {"home_win": home_odds, "away_win": away_odds},
                "market_rules": _MARKET_RULES,
                "edge_home": edge_home,
                "edge_away": edge_away,
                "no_bet_reason": no_bet_reason,
                "comparable": comparable,
                "outcome_home_win": valid_target,
                "price_age_seconds": _number(row["price_age_seconds"]),
            }
        )
    simulator = BettingSimulator(
        initial_bankroll=config.initial_bankroll,
        stake_strategy="flat",
        flat_stake=config.flat_stake,
        min_edge_threshold=config.min_edge,
        max_stake_fraction=config.max_stake_fraction,
    )
    result = simulator.simulate(
        np.asarray(selected_outcome),
        np.asarray(selected_p),
        np.asarray(selected_odds),
        return_event_trace=True,
        bet_eligible_mask=np.asarray(allowed),
    )
    assert result.event_trace is not None
    traces = []
    for trace_row, sim in zip(rows, result.event_trace.to_dict(orient="records"), strict=True):
        trace_row.update(
            {
                "bet_placed": bool(sim["bet_placed"]),
                "stake": float(sim["stake"]),
                "outcome_selected": int(sim["y_true"]) if trace_row["selected_side"] else None,
                "profit": float(sim["profit"]),
                "cumulative_bankroll": float(sim["bankroll_after"]),
            }
        )
        traces.append(trace_row)
    trace_df = result.event_trace
    trace_df["bet_placed"] = np.asarray(allowed) & trace_df["bet_placed"].to_numpy(dtype=bool)
    return (
        {
            "n_bets": result.n_bets,
            "turnover": result.turnover_units,
            "profit_units": result.profit_units,
            "roi_percent": result.roi,
            "max_drawdown_units": result.max_drawdown_units,
            "max_drawdown_percent": result.max_drawdown_pct * 100,
            "final_bankroll": result.final_bankroll,
            "trace": traces,
        },
        trace_df,
    )


def evaluate_events(
    events: pd.DataFrame,
    *,
    config: FinancialEvaluationConfig | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Оценить candidate и baseline на общем Pinnacle line/comparable universe."""
    config = config or FinancialEvaluationConfig()
    frame = _validate_events(events)
    frame["_target"] = pd.to_numeric(frame["home_win"], errors="coerce")
    expected = len(frame)
    eligible_line = frame["coverage"].eq("covered")
    common = {
        "expected_universe": expected,
        "eligible_line": int(eligible_line.sum()),
        "comparable": 0,
        "placed_bets": 0,
    }
    output_models: dict[str, Any] = {}
    traces: dict[str, pd.DataFrame] = {}
    month_counts: dict[str, int] = {}
    for prefix in ("candidate", "baseline"):
        ml = _ml_metrics(frame, prefix)
        financial, trace = _model_trace(frame, prefix, config)
        traces[prefix] = trace
        if prefix == "candidate":
            common["comparable"] = ml["n"]
            common["placed_bets"] = financial["n_bets"]
            placed = pd.DataFrame(financial["trace"])
            if not placed.empty:
                bets = placed[placed["bet_placed"]]
                month_counts = {
                    str(month): int(count)
                    for month, count in bets["kickoff_utc"].str.slice(0, 7).value_counts().items()
                }
        bets_trace = trace[trace["bet_placed"]].copy()
        degenerate = len(bets_trace) < 2 or bets_trace["profit"].nunique(dropna=False) < 2
        if len(bets_trace) < config.min_bets or degenerate:
            bootstrap = {
                "status": "insufficient_or_degenerate_sample",
                "n_resamples": 0,
                "positive_roi_fraction": None,
                "roi_ci_percent": None,
            }
        else:
            boot = BlockBootstrap(
                bets_trace,
                n_resamples=config.n_bootstrap,
                min_block_length=config.min_block_length,
                max_block_length=config.max_block_length,
                seed=config.seed,
                confidence_level=0.95,
                initial_bankroll=config.initial_bankroll,
            ).run()
            roi = boot.metrics.get("roi")
            bootstrap = {
                "status": "ok",
                "n_resamples": boot.n_resamples,
                "positive_roi_fraction": boot.positive_roi_fraction,
                "roi_ci_percent": [roi.ci_lower, roi.ci_upper] if roi else None,
            }
        output_models[prefix] = {"ml_metrics": ml, **financial, "bootstrap": bootstrap}
    candidate = output_models["candidate"]
    sensitivity: dict[str, Any] = {}
    for hours in (1, 6):
        financial, _ = _model_trace(frame, "candidate", config, max_price_age_seconds=hours * 3600)
        sensitivity[f"max_age_{hours}h"] = {
            key: financial[key] for key in ("n_bets", "turnover", "profit_units", "roi_percent")
        }
    exclusions: dict[str, int] = {}
    for _, row in frame.iterrows():
        if row["coverage"] != "covered":
            reason = str(row["coverage"])
        elif _number(row["candidate_home"]) is None or _number(row["baseline_home"]) is None:
            reason = "missing_oos_prediction"
        elif _number(row["home_win"]) is None:
            reason = "invalid_outcome"
        else:
            continue
        exclusions[reason] = exclusions.get(reason, 0) + 1
    candidate_month_count = len(month_counts)
    enough = (
        common["comparable"] >= config.min_comparable
        and candidate["n_bets"] >= config.min_bets
        and candidate_month_count >= config.min_bet_months
    )
    evidence_sufficient = enough and candidate["bootstrap"]["status"] == "ok"
    gates = {
        "positive_roi": candidate["roi_percent"] > 0,
        "bootstrap_positive_fraction": candidate["bootstrap"]["positive_roi_fraction"] is not None
        and candidate["bootstrap"]["positive_roi_fraction"]
        >= config.min_positive_bootstrap_fraction,
        "bet_coverage": common["eligible_line"] > 0
        and candidate["n_bets"] / common["eligible_line"] >= config.min_bet_coverage,
        "profit_above_baseline": candidate["profit_units"]
        > output_models["baseline"]["profit_units"],
        "minimum_evidence": enough,
    }
    reasons = [key for key, passed in gates.items() if not passed]
    if candidate["bootstrap"]["status"] != "ok":
        reasons.append("bootstrap_insufficient_or_degenerate_sample")
    financial_status = (
        "insufficient_evidence" if not evidence_sufficient else "pass" if not reasons else "fail"
    )
    return {
        "format": "sports-forecast-financial-evaluation",
        "format_version": 1,
        "market_rules": _MARKET_RULES,
        "config": config.__dict__,
        "denominators": common,
        "coverage": {
            "line_coverage_expected_universe": common["eligible_line"] / expected
            if expected
            else 0.0,
            "comparable_of_eligible_line": common["comparable"] / common["eligible_line"]
            if common["eligible_line"]
            else 0.0,
            "bet_coverage_eligible_line": candidate["n_bets"] / common["eligible_line"]
            if common["eligible_line"]
            else 0.0,
        },
        "exclusions": exclusions,
        "models": output_models,
        "sensitivity": sensitivity,
        "months_with_candidate_bets": candidate_month_count,
        "gates": gates,
        "financial_gate_status": financial_status,
        "research_decision": "pending_independent_review",
        "decision_reasons": reasons,
        "provenance": {
            **(provenance or {}),
            "priced_snapshots": int(eligible_line.sum()),
            "retrieved_at_unknown": int((eligible_line & frame["retrieved_at"].isna()).sum()),
            "late_retrievals": int(
                (
                    eligible_line
                    & frame.get("late_retrieval", pd.Series(False, index=frame.index)).map(
                        lambda value: isinstance(value, (bool, np.bool_)) and bool(value)
                    )
                ).sum()
            ),
            "provider_as_of_only": True,
        },
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _provider_rows_for_prediction_window(
    provider_rows: list[dict[str, Any]],
    op_window: dict[str, Any],
    provider_window: dict[str, Any],
    cli_end: str,
) -> list[dict[str, Any]]:
    """Выбрать полуоткрытое окно op1 внутри закреплённого pd1."""
    lower = pd.Timestamp(op_window.get("start_utc"))
    upper = pd.Timestamp(op_window.get("end_utc_exclusive"))
    provider_lower = pd.Timestamp(provider_window.get("window_start_utc"))
    provider_upper = pd.Timestamp(provider_window.get("window_end_utc_exclusive"))
    if any(stamp.tz is None for stamp in (lower, upper, provider_lower, provider_upper)):
        raise ValueError("Временные границы op1 и pd1 должны содержать часовой пояс")
    if lower < provider_lower or upper > provider_upper or lower >= upper:
        raise ValueError("Окно op1 должно полностью входить в окно pd1")
    if upper != pd.Timestamp(cli_end):
        raise ValueError(
            "Параметр CLI end должен совпадать с исключённой верхней границей окна op1"
        )
    selected = [row for row in provider_rows if lower <= pd.Timestamp(row["kickoff_utc"]) < upper]
    if len(selected) != len({str(row.get("source_event_id")) for row in selected}):
        raise ValueError("В окне op1 набор pd1 содержит повторные event ID")
    return selected


def _verify_op1_contract(
    manifest: dict[str, Any],
    predictions: list[dict[str, Any]],
    training_events: pd.DataFrame,
    lower: str,
    upper: str,
    confirmed_team_codes: set[str],
) -> None:
    """Проверить объявленные model/config/features и месячные training claims op1."""
    expected_allowlist = ["weekday_utc", "hour_utc", "home_team_one_hot", "away_team_one_hot"]
    expected_rules = _MARKET_RULES
    if manifest.get("model_config") != oos_contract._MODEL_CONFIG:
        raise ValueError("model_config manifest op1 не соответствует зафиксированному протоколу")
    if manifest.get("feature_version") != oos_contract._FEATURE_VERSION:
        raise ValueError("feature_version manifest op1 не соответствует зафиксированному протоколу")
    if manifest.get("feature_allowlist") != expected_allowlist:
        raise ValueError(
            "feature_allowlist manifest op1 не соответствует зафиксированному протоколу"
        )
    if manifest.get("market_rules") != expected_rules:
        raise ValueError("market_rules manifest op1 не соответствует winner_withOT")
    if manifest.get("training_window_start_utc") != oos_contract._iso(oos_contract._TRAINING_START):
        raise ValueError("training start op1 не соответствует зафиксированному протоколу")
    if manifest.get("team_vocabulary_cutoff_utc") != oos_contract._iso(
        oos_contract._TEAM_VOCAB_CUTOFF
    ):
        raise ValueError("team vocabulary cutoff op1 не соответствует протоколу")
    vocabulary_rows = training_events.copy()
    vocabulary_rows["_kickoff"] = pd.to_datetime(
        vocabulary_rows["kickoff_utc"], utc=True, errors="raise"
    )
    vocabulary_rows = vocabulary_rows[
        (vocabulary_rows["_kickoff"] >= oos_contract._TRAINING_START)
        & (vocabulary_rows["_kickoff"] <= oos_contract._TEAM_VOCAB_CUTOFF)
        & vocabulary_rows["team_identity_eligible"].fillna(False).astype(bool)
    ]
    expected_vocabulary = sorted(
        {
            str(team)
            for _, row in vocabulary_rows.iterrows()
            for team in (row["home_team"], row["away_team"])
            if str(team) in confirmed_team_codes
        }
    )
    if manifest.get("team_feature_vocabulary") != expected_vocabulary:
        raise ValueError("team_feature_vocabulary op1 отличается от verified raw NHL данных")

    lower_ts, upper_ts = pd.Timestamp(lower), pd.Timestamp(upper)
    steps = manifest.get("training_steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("В op1 отсутствуют помесячные training_steps")
    step_by_month: dict[str, dict[str, Any]] = {}
    raw_by_source = {
        str(row["source_event_id"]): row for row in training_events.to_dict(orient="records")
    }
    if len(raw_by_source) != len(training_events):
        raise ValueError("Raw NHL training events содержат повторный source ID")
    for step in steps:
        month = pd.Timestamp(step["month_start_utc"])
        if month.tz is None or month.day != 1 or not lower_ts <= month < upper_ts:
            raise ValueError("Месячный training step выходит за окно op1")
        month_iso = oos_contract._iso(month)
        cutoff = month - pd.Timedelta(days=7)
        ids = step.get("train_source_ids")
        if not isinstance(ids, list) or not ids or len(ids) != len(set(map(str, ids))):
            raise ValueError("training step содержит пустой или повторный список source IDs")
        ids_hash = oos_contract._sha256(oos_contract._canonical_bytes(ids))
        if (
            step.get("source_ids_sha256") != ids_hash
            or step.get("train_row_count") != len(ids)
            or step.get("label_availability_cutoff_utc") != month_iso
            or step.get("kickoff_cutoff_utc") != oos_contract._iso(cutoff)
            or step.get("label_availability_proxy") != "kickoff_plus_7d"
        ):
            raise ValueError("training step hashes/count/cutoffs не совпадают с protocol")
        expected_ids = [
            str(row["source_event_id"])
            for row in sorted(
                training_events.to_dict(orient="records"),
                key=lambda item: (pd.Timestamp(item["kickoff_utc"]), str(item["source_event_id"])),
            )
            if bool(row.get("team_identity_eligible", False))
            and pd.Timestamp(row["kickoff_utc"]) >= oos_contract._TRAINING_START
            and pd.Timestamp(row["kickoff_utc"]) <= cutoff
            and oos_contract._winner_with_ot_target(pd.Series(row)) is not None
        ]
        if list(map(str, ids)) != expected_ids:
            raise ValueError(
                "training source IDs не покрывают полный ordered eligible set из verified raw"
            )
        for source_id in ids:
            row = raw_by_source.get(str(source_id))
            if row is None or not bool(row.get("team_identity_eligible", False)):
                raise ValueError("training source ID отсутствует в проверенном raw NHL наборе")
            kickoff = pd.Timestamp(row["kickoff_utc"])
            if kickoff.tz is None or kickoff + pd.Timedelta(days=7) > month:
                raise ValueError("training source event пересекает label availability cutoff")
            if (
                _settled_home_winner(row["status"], row["home_score_ft"], row["away_score_ft"])
                is None
            ):
                raise ValueError("training source event не имеет завершённого валидного target")
        if month_iso in step_by_month:
            raise ValueError("op1 повторяет monthly training step")
        step_by_month[month_iso] = step

    for prediction in predictions:
        month_iso = str(prediction.get("month_start_utc"))
        step = step_by_month.get(month_iso)
        if step is None:
            raise ValueError("op1 prediction не ссылается на training step")
        month = pd.Timestamp(month_iso)
        kickoff_cutoff = oos_contract._iso(month - pd.Timedelta(days=7))
        if (
            prediction.get("oos_basis") != "monthly_walk_forward"
            or prediction.get("training_cutoff_utc") != month_iso
            or prediction.get("kickoff_cutoff_utc") != kickoff_cutoff
            or prediction.get("label_availability_proxy") != "kickoff_plus_7d"
            or prediction.get("train_source_ids_sha256") != step["source_ids_sha256"]
            or prediction.get("train_row_count") != step["train_row_count"]
        ):
            raise ValueError("op1 prediction training cutoff/hash отличается от training step")
        name = prediction.get("model_name")
        if name not in {"candidate", "baseline"}:
            raise ValueError("op1 содержит неизвестную модель")
        model_config: Any = (
            oos_contract._MODEL_CONFIG if name == "candidate" else "home_win_frequency_beta_1_1_v1"
        )
        config_id = oos_contract._sha256(
            oos_contract._canonical_bytes(
                {
                    "feature_version": oos_contract._FEATURE_VERSION,
                    "model": name,
                    "model_config": model_config,
                }
            )
        )
        model_id = oos_contract._sha256(
            oos_contract._canonical_bytes(
                {
                    "name": name,
                    "config": model_config,
                    "training_cutoff_utc": month_iso,
                    "train_source_ids_sha256": step["source_ids_sha256"],
                }
            )
        )
        feature_hash = oos_contract._sha256(
            oos_contract._canonical_bytes(
                {
                    "feature_version": oos_contract._FEATURE_VERSION,
                    **prediction.get("feature_values", {}),
                }
            )
        )
        raw_event = raw_by_source.get(str(prediction.get("source_event_id")))
        if raw_event is None:
            raise ValueError("op1 source event отсутствует в verified raw NHL данных")
        raw_kickoff = pd.Timestamp(raw_event["kickoff_utc"])
        expected_features = {
            "weekday_utc": int(raw_kickoff.dayofweek),
            "hour_utc": int(raw_kickoff.hour),
            "home_team": str(raw_event["home_team"]),
            "away_team": str(raw_event["away_team"]),
        }
        feature_values = {
            "weekday_utc": float(raw_kickoff.dayofweek),
            "hour_utc": float(raw_kickoff.hour),
        }
        for team in expected_vocabulary:
            feature_values[f"home_team_{team}"] = float(raw_event["home_team"] == team)
            feature_values[f"away_team_{team}"] = float(raw_event["away_team"] == team)
        if (
            prediction.get("features") != expected_features
            or prediction.get("feature_values") != feature_values
        ):
            raise ValueError("op1 features не пересчитываются из verified kickoff/teams")
        if prediction.get("config_id") != config_id or prediction.get("model_id") != model_id:
            raise ValueError("op1 model/config ID не соответствует config и training step")
        if prediction.get("feature_hash") != feature_hash:
            raise ValueError("op1 feature hash не соответствует feature values")


def run_verified_evaluation(
    *,
    matches_path: Path,
    team_seed_path: Path,
    universe_path: Path,
    provider_manifest_path: Path,
    snapshot_path: Path,
    historical_database_path: Path,
    prediction_manifest_path: Path,
    end: str,
    mode: str,
    output_dir: Path,
    config: FinancialEvaluationConfig | None = None,
) -> Path:
    """Проверить pd1/op1/ir1/raw provenance, затем создать trace и report."""
    end_ts = pd.Timestamp(end)
    limit = pd.Timestamp("2024-10-01T00:00:00Z")
    if mode == "development" and end_ts > limit:
        raise ValueError("Engineering development mode ограничен событиями до 2024-10-01")
    if mode not in {"development", "final"}:
        raise ValueError("mode должен быть development или final")
    predictions_manifest_path = Path(prediction_manifest_path)
    op = json.loads(predictions_manifest_path.read_text(encoding="utf-8"))
    if op.get("format") != "sports-forecast-oos-predictions" or op.get("format_version") != 1:
        raise ValueError("Некорректный manifest op1")
    prediction_path = predictions_manifest_path.with_name(
        op["prediction_id"].split(":", 1)[1] + ".jsonl"
    )
    raw_predictions = prediction_path.read_bytes()
    if op.get("predictions_sha256") != "sha256:" + hashlib.sha256(raw_predictions).hexdigest():
        raise ValueError("Fingerprint прогнозов op1 не совпадает")
    if op.get("prediction_id") != "op1:" + hashlib.sha256(raw_predictions).hexdigest():
        raise ValueError("ID прогнозов op1 не совпадает с содержимым")
    events, raw_fingerprints, dataset_id, snapshot_id, confirmed_team_codes = load_verified_input(
        matches_path=Path(matches_path),
        team_seed_path=Path(team_seed_path),
        universe_path=Path(universe_path),
        provider_manifest_path=Path(provider_manifest_path),
        snapshot_path=Path(snapshot_path),
        historical_database_path=Path(historical_database_path),
        end=end,
    )
    if op.get("dataset_id") != dataset_id or op.get("registry_snapshot_id") != snapshot_id:
        raise ValueError("Ссылки op1 на pd1/ir1 не совпадают с проверенными входами")
    if op.get("source_fingerprints") != raw_fingerprints:
        raise ValueError("Source fingerprints op1 не совпадают с проверенными входами")
    provider_manifest = json.loads(Path(provider_manifest_path).read_text(encoding="utf-8"))
    provider_events_path = Path(provider_manifest_path).parent / "events.jsonl"
    provider_rows = [
        json.loads(line) for line in provider_events_path.read_text(encoding="utf-8").splitlines()
    ]
    predictions = [json.loads(line) for line in raw_predictions.decode().splitlines()]
    window = op.get("window", {})
    _verify_op1_contract(
        op,
        predictions,
        events,
        str(window.get("start_utc")),
        str(window.get("end_utc_exclusive")),
        confirmed_team_codes,
    )
    if any(
        row.get("dataset_id") != dataset_id or row.get("registry_snapshot_id") != snapshot_id
        for row in predictions
    ):
        raise ValueError("Происхождение строки op1 не совпадает с проверенными pd1/ir1")
    pred_by_event: dict[str, dict[str, dict[str, Any]]] = {}
    for row in predictions:
        event_id = str(row["project_event_id"])
        model_name = str(row["model_name"])
        if model_name not in {"candidate", "baseline"} or model_name in pred_by_event.setdefault(
            event_id, {}
        ):
            raise ValueError("В op1 повторена или не поддерживается пара model/event")
        pred_by_event[event_id][model_name] = row
    if any(set(models) != {"candidate", "baseline"} for models in pred_by_event.values()):
        raise ValueError("Для каждого события op1 должен содержать candidate и baseline")
    if int(op.get("expected_oos_events", -1)) != len(pred_by_event):
        raise ValueError("Число OOS событий не совпадает с manifest op1")
    provider_rows = _provider_rows_for_prediction_window(
        provider_rows,
        op.get("window", {}),
        provider_manifest.get("resolved_config", {}),
        end,
    )
    expected_op_events = {
        str(row.get("project_event_id"))
        for row in provider_rows
        if row.get("coverage") == "covered" and row.get("project_event_id")
    }
    if set(pred_by_event) != expected_op_events:
        raise ValueError("Набор событий op1 отличается от пригодных по цене событий pd1 в его окне")
    all_event_frame = events
    report_rows: list[dict[str, Any]] = []
    for record in provider_rows:
        source_id = str(record["source_event_id"])
        event_id = str(record.get("project_event_id") or "")
        raw_match = all_event_frame.loc[
            all_event_frame["source_event_id"].astype(str).eq(source_id)
        ]
        target: int | None = None
        if len(raw_match) > 1:
            raise ValueError("В исходном NHL наборе повторён source event")
        if len(raw_match) == 1:
            raw = raw_match.iloc[0]
            if not _same_instant(raw["kickoff_utc"], record["kickoff_utc"]):
                raise ValueError("Kickoff исходного NHL события отличается от pd1")
            if event_id and str(raw["project_event_id"]) != event_id:
                raise ValueError("Project event UUID исходного NHL события отличается от pd1")
            target = _settled_home_winner(raw["status"], raw["home_score_ft"], raw["away_score_ft"])
        model_rows = pred_by_event.get(event_id, {})
        if event_id and model_rows and record.get("coverage") != "covered":
            raise ValueError("Прогнозы op1 должны указывать на события pd1 с пригодной ценой")
        if model_rows and target is None:
            raise ValueError("Для события op1 нет корректного settled исхода winner_withOT")
        candidate_row = model_rows.get("candidate", {})
        baseline_row = model_rows.get("baseline", {})
        for prediction in (candidate_row, baseline_row):
            if prediction and (
                str(prediction.get("source_event_id")) != source_id
                or str(prediction.get("project_event_id")) != event_id
                or not _same_instant(prediction.get("kickoff_utc"), record["kickoff_utc"])
                or not _same_instant(prediction.get("decision_at"), record["decision_at"])
                or prediction.get("market") != _MARKET_RULES["market"]
                or {**prediction.get("market_rules", {}), "market": prediction.get("market")}
                != _MARKET_RULES
            ):
                raise ValueError("Идентичность события, market или время op1 отличается от pd1")
        price = record.get("price") or {}
        prices = price.get("prices", {})
        probabilities_c = candidate_row.get("probabilities", {})
        probabilities_b = baseline_row.get("probabilities", {})
        report_rows.append(
            {
                "project_event_id": event_id or f"unresolved:{source_id}",
                "source_event_id": source_id,
                "kickoff_utc": record["kickoff_utc"],
                "decision_at": record["decision_at"],
                "home_win": target,
                "home_odds": prices.get("home_win"),
                "away_odds": prices.get("away_win"),
                "price_age_seconds": price.get("age_seconds"),
                "coverage": record["coverage"],
                "retrieved_at": price.get("retrieved_at"),
                "observed_at": price.get("observed_at"),
                "retrieval_status": price.get("retrieval_status"),
                "late_retrieval": price.get("late_retrieval"),
                "observation_id": price.get("observation_id"),
                "receipt_id": price.get("receipt_id"),
                "source_file_sha256": price.get("source_file_sha256"),
                "registry_snapshot_id": price.get("ir1"),
                "candidate_home": probabilities_c.get("home_win"),
                "candidate_away": probabilities_c.get("away_win"),
                "baseline_home": probabilities_b.get("home_win"),
                "baseline_away": probabilities_b.get("away_win"),
                "candidate_model_id": candidate_row.get("model_id"),
                "baseline_model_id": baseline_row.get("model_id"),
                "candidate_config_id": candidate_row.get("config_id"),
                "baseline_config_id": baseline_row.get("config_id"),
            }
        )
    report = evaluate_events(
        pd.DataFrame(report_rows),
        config=config,
        provenance={
            "dataset_id": dataset_id,
            "prediction_id": op["prediction_id"],
            "registry_snapshot_id": snapshot_id,
            "provider_events_sha256": provider_manifest["events_sha256"],
            "raw_matches_sha256": _sha256_file(Path(matches_path)),
            "prediction_feature_version": op.get("feature_version"),
            "prediction_model_config": op.get("model_config"),
            "code_fingerprints": {
                "financial_evaluator": _sha256_file(Path(__file__)),
                "betting_simulator": _sha256_file(
                    Path(__file__).resolve().parents[1] / "betting" / "simulator.py"
                ),
                "block_bootstrap": _sha256_file(
                    Path(__file__).resolve().parents[1] / "betting" / "bootstrap.py"
                ),
                "oos_prediction_contract": _sha256_file(
                    Path(__file__).with_name("oos_predictions.py")
                ),
            },
            "retrieval_note": "retrieved_at=null означает неизвестное время получения; observed_at — provider-as-of",
        },
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_bytes = b"".join(
        _canonical(row) + b"\n"
        for name in ("candidate", "baseline")
        for row in report["models"][name]["trace"]
    )
    report["trace_sha256"] = "sha256:" + hashlib.sha256(trace_bytes).hexdigest()
    report_bytes = _canonical(report) + b"\n"
    report_id = "ev1:" + hashlib.sha256(report_bytes).hexdigest()
    report_path = output_dir / f"{report_id.split(':', 1)[1]}.json"
    traces_path = output_dir / f"{report_id.split(':', 1)[1]}.traces.jsonl"
    for path, payload in ((report_path, report_bytes), (traces_path, trace_bytes)):
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Существующий evaluation artifact конфликтует с повторным запуском")
        if not path.exists():
            path.write_bytes(payload)
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Общая финансовая оценка проверенных OOS прогнозов"
    )
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--team-seed", type=Path, required=True)
    parser.add_argument("--universe-manifest", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--prediction-manifest", type=Path, required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--mode", choices=("development", "final"), default="development")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = run_verified_evaluation(
        matches_path=args.matches,
        team_seed_path=args.team_seed,
        universe_path=args.universe_manifest,
        provider_manifest_path=args.provider_manifest,
        snapshot_path=args.snapshot,
        historical_database_path=args.historical_database,
        prediction_manifest_path=args.prediction_manifest,
        end=args.end,
        mode=args.mode,
        output_dir=args.output,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
