"""Synthetic contracts for the shared financial evaluator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sports_forecast.research.financial_evaluator import (
    FinancialEvaluationConfig,
    _provider_rows_for_prediction_window,
    _settled_home_winner,
    _verify_op1_contract,
    evaluate_events,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "project_event_id": "e1",
                "source_event_id": "s1",
                "kickoff_utc": "2024-09-01T00:00:00Z",
                "decision_at": "2024-08-31T23:45:00Z",
                "home_win": 1,
                "home_odds": 2.2,
                "away_odds": 1.8,
                "price_age_seconds": 60,
                "candidate_home": 0.70,
                "candidate_away": 0.30,
                "baseline_home": 0.50,
                "baseline_away": 0.50,
                "coverage": "covered",
                "retrieved_at": "2024-08-31T23:46:00Z",
                "retrieval_status": "known",
                "late_retrieval": True,
            },
            {
                "project_event_id": "e2",
                "source_event_id": "s2",
                "kickoff_utc": "2024-09-02T00:00:00Z",
                "decision_at": "2024-09-01T23:45:00Z",
                "home_win": 0,
                "home_odds": 1 / 0.6,
                "away_odds": 5.0,
                "price_age_seconds": 60,
                "candidate_home": 0.7,
                "candidate_away": 0.3,
                "baseline_home": 0.7,
                "baseline_away": 0.3,
                "coverage": "covered",
                "retrieved_at": None,
            },
            {
                "project_event_id": "e3",
                "source_event_id": "s3",
                "kickoff_utc": "2024-09-03T00:00:00Z",
                "decision_at": "2024-09-02T23:45:00Z",
                "home_win": 0,
                "home_odds": None,
                "away_odds": None,
                "price_age_seconds": None,
                "candidate_home": 0.4,
                "candidate_away": 0.6,
                "baseline_home": 0.5,
                "baseline_away": 0.5,
                "coverage": "no_line",
                "retrieved_at": None,
            },
            {
                "project_event_id": "e4",
                "source_event_id": "s4",
                "kickoff_utc": "2024-09-04T00:00:00Z",
                "decision_at": "2024-09-03T23:45:00Z",
                "home_win": 1,
                "home_odds": 2.2,
                "away_odds": 1.8,
                "price_age_seconds": 7200,
                "candidate_home": 0.2,
                "candidate_away": 0.8,
                "baseline_home": 0.5,
                "baseline_away": 0.5,
                "coverage": "covered",
                "retrieved_at": None,
            },
        ]
    )


def test_evaluator_uses_trace_for_finance_and_preserves_tie_no_bet() -> None:
    result = evaluate_events(
        _events(),
        config=FinancialEvaluationConfig(n_bootstrap=20, min_block_length=1, max_block_length=2),
    )
    candidate = result["models"]["candidate"]
    trace = candidate["trace"]
    assert [row["selected_side"] for row in trace] == ["home_win", None, None, "away_win"]
    assert trace[1]["no_bet_reason"] == "equal_max_edge"
    assert trace[3]["profit"] == -10
    assert trace[3]["cumulative_bankroll"] == 1002
    assert trace[0]["edge_home"] == pytest.approx(0.70 - 1 / 2.2)
    assert candidate["profit_units"] == pytest.approx(sum(row["profit"] for row in trace)) == 2
    assert candidate["roi_percent"] == pytest.approx(10)
    assert result["denominators"] == {
        "expected_universe": 4,
        "eligible_line": 3,
        "comparable": 3,
        "placed_bets": 2,
    }
    assert result["coverage"]["bet_coverage_eligible_line"] == pytest.approx(2 / 3)
    assert result["provenance"]["retrieved_at_unknown"] == 2
    assert result["provenance"]["late_retrievals"] == 1
    assert result["research_decision"] == "pending_independent_review"
    assert result["models"]["baseline"]["n_bets"] == 0
    assert result["sensitivity"]["max_age_1h"]["n_bets"] == 1
    assert result["sensitivity"]["max_age_6h"]["n_bets"] == 2


def test_evaluator_rejects_non_simplex_probabilities_and_duplicate_events() -> None:
    events = _events()
    events.loc[0, "candidate_away"] = 0.31
    with pytest.raises(ValueError, match="вероятности"):
        evaluate_events(events, config=FinancialEvaluationConfig(n_bootstrap=0))
    events = _events()
    events.loc[1, "project_event_id"] = "e1"
    with pytest.raises(ValueError, match="дубликат"):
        evaluate_events(events, config=FinancialEvaluationConfig(n_bootstrap=0))
    events = _events()
    events.loc[0, "decision_at"] = "2024-08-31T23:44:00Z"
    with pytest.raises(ValueError, match="decision_at"):
        evaluate_events(events, config=FinancialEvaluationConfig(n_bootstrap=0))
    events = _events()
    events.loc[0, "baseline_home"] = np.nan
    events.loc[0, "baseline_away"] = np.nan
    with pytest.raises(ValueError, match="одинаковый набор"):
        evaluate_events(events, config=FinancialEvaluationConfig(n_bootstrap=0))
    events = _events()
    events.loc[0, "price_age_seconds"] = 86401
    with pytest.raises(ValueError, match="24 часов"):
        evaluate_events(events, config=FinancialEvaluationConfig(n_bootstrap=0))


def test_financial_gate_pass_never_makes_research_decision() -> None:
    result = evaluate_events(
        _events(),
        config=FinancialEvaluationConfig(
            n_bootstrap=50,
            min_block_length=1,
            max_block_length=2,
            min_comparable=1,
            min_bets=1,
            min_bet_months=1,
            min_positive_bootstrap_fraction=0,
            min_bet_coverage=0,
        ),
    )
    assert result["financial_gate_status"] == "pass"
    assert result["research_decision"] == "pending_independent_review"


def test_provider_window_is_half_open_and_ignores_rows_outside_op1() -> None:
    provider_rows = [
        {"source_event_id": "before", "kickoff_utc": "2023-09-30T23:59:59Z"},
        {"source_event_id": "start", "kickoff_utc": "2023-10-01T00:00:00Z"},
        {"source_event_id": "inside", "kickoff_utc": "2024-09-30T23:59:59Z"},
        {"source_event_id": "end", "kickoff_utc": "2024-10-01T00:00:00Z"},
    ]
    selected = _provider_rows_for_prediction_window(
        provider_rows,
        {"start_utc": "2023-10-01T00:00:00Z", "end_utc_exclusive": "2024-10-01T00:00:00Z"},
        {
            "window_start_utc": "2023-10-01T00:00:00Z",
            "window_end_utc_exclusive": "2026-05-01T00:00:00Z",
        },
        "2024-10-01T00:00:00Z",
    )
    assert [row["source_event_id"] for row in selected] == ["start", "inside"]


def test_provider_window_rejects_mismatch_or_partial_dataset_coverage() -> None:
    op_window = {"start_utc": "2023-09-01T00:00:00Z", "end_utc_exclusive": "2024-10-01T00:00:00Z"}
    provider_window = {
        "window_start_utc": "2023-10-01T00:00:00Z",
        "window_end_utc_exclusive": "2026-05-01T00:00:00Z",
    }
    with pytest.raises(ValueError, match="входить"):
        _provider_rows_for_prediction_window([], op_window, provider_window, "2024-10-01T00:00:00Z")
    with pytest.raises(ValueError, match="CLI end"):
        _provider_rows_for_prediction_window(
            [],
            {**op_window, "start_utc": "2023-10-01T00:00:00Z"},
            provider_window,
            "2024-09-30T00:00:00Z",
        )


@pytest.mark.parametrize("home_score,away_score", [(-1, 0), (1.5, 0), (float("inf"), 1), (2, 2)])
def test_settlement_rejects_invalid_finished_scores(home_score: float, away_score: float) -> None:
    with pytest.raises(ValueError, match="голы|равный"):
        _settled_home_winner("finished", home_score, away_score)


def test_settlement_accepts_valid_overtime_scores_and_skips_unfinished() -> None:
    assert _settled_home_winner("finished", 4, 3) == 1
    assert _settled_home_winner("finished", 2, 3) == 0
    assert _settled_home_winner("scheduled", None, None) is None


def test_op1_verifier_rejects_tampered_model_config() -> None:
    from sports_forecast.research import oos_predictions

    manifest = {"model_config": {**oos_predictions._MODEL_CONFIG, "C": 7.0}}
    with pytest.raises(ValueError, match="model_config"):
        _verify_op1_contract(
            manifest,
            [],
            pd.DataFrame(),
            "2023-10-01T00:00:00Z",
            "2024-10-01T00:00:00Z",
            {"BOS", "NYR"},
        )


def test_op1_verifier_rejects_omitted_eligible_training_source() -> None:
    from sports_forecast.research import oos_predictions

    training = pd.DataFrame(
        [
            {
                "source_event_id": "early",
                "kickoff_utc": "2020-01-01T00:00:00Z",
                "home_team": "BOS",
                "away_team": "NYR",
                "status": "finished",
                "home_score_ft": 2,
                "away_score_ft": 1,
                "team_identity_eligible": True,
            },
            {
                "source_event_id": "later",
                "kickoff_utc": "2020-01-02T00:00:00Z",
                "home_team": "NYR",
                "away_team": "BOS",
                "status": "finished",
                "home_score_ft": 1,
                "away_score_ft": 2,
                "team_identity_eligible": True,
            },
        ]
    )
    month = "2024-10-01T00:00:00Z"
    ids = ["early"]  # Deliberately omit the second eligible verified raw event.
    ids_hash = oos_predictions._sha256(oos_predictions._canonical_bytes(ids))
    manifest = {
        "model_config": oos_predictions._MODEL_CONFIG,
        "feature_version": oos_predictions._FEATURE_VERSION,
        "feature_allowlist": ["weekday_utc", "hour_utc", "home_team_one_hot", "away_team_one_hot"],
        "market_rules": {
            "market": "winner_withOT",
            "outcomes": ["home_win", "away_win"],
            "overtime": True,
            "shootout": True,
            "draw": False,
        },
        "training_window_start_utc": oos_predictions._iso(oos_predictions._TRAINING_START),
        "team_vocabulary_cutoff_utc": oos_predictions._iso(oos_predictions._TEAM_VOCAB_CUTOFF),
        "team_feature_vocabulary": ["BOS", "NYR"],
        "training_steps": [
            {
                "month_start_utc": month,
                "label_availability_cutoff_utc": month,
                "kickoff_cutoff_utc": "2024-09-24T00:00:00Z",
                "label_availability_proxy": "kickoff_plus_7d",
                "source_ids_sha256": ids_hash,
                "train_row_count": len(ids),
                "train_source_ids": ids,
            }
        ],
    }

    with pytest.raises(ValueError, match="полный ordered eligible set"):
        _verify_op1_contract(
            manifest,
            [],
            training,
            "2024-10-01T00:00:00Z",
            "2024-11-01T00:00:00Z",
            {"BOS", "NYR"},
        )
