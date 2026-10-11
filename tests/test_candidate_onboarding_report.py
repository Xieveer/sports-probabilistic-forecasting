"""Отчёт кандидата привязан к проверенному run и данным турнира."""

from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.config.portfolio import load_portfolio_catalog
from sports_forecast.training.candidate_report import build_tournament_candidate_report


CATALOG = load_portfolio_catalog(
    Path(__file__).resolve().parents[1] / "conf/portfolio/default.yaml"
)
METRICS = {
    "test_logloss": 0.63,
    "test_auc": 0.64,
    "test_brier": 0.22,
    "betting_roi": -12.0,
    "betting_coverage": 1.0,
    "betting_n_bets": 20.0,
}
TRACE = pd.DataFrame(
    {
        "bet_placed": [i < 20 for i in range(30)],
        "stake": [10.0 if i < 20 else 0.0 for i in range(30)],
        "profit": [(-10.0 if i % 3 == 0 else 15.0) if i < 20 else 0.0 for i in range(30)],
        "y_true": [0 if i % 3 == 0 else 1 for i in range(30)],
        "datetime": pd.date_range("2026-01-01", periods=30, freq="D").astype(str),
        "id": [f"m{i // 2}" for i in range(30)],
    }
)


def test_report_keeps_candidate_state_and_real_metrics() -> None:
    report = build_tournament_candidate_report(
        CATALOG,
        "premier_league_winner",
        run_id="run-1",
        run_status="FINISHED",
        tags={"tournament": "premier_league", "market_spec": "winner"},
        metrics=METRICS,
        bet_trace=TRACE,
        competition_codes={"ENG1"},
        data_sha256="a" * 64,
        data_rows=4,
    )

    assert report["state"] == "candidate"
    assert report["run_id"] == "run-1"
    assert report["ml_metrics"]["logloss"] == 0.63
    assert report["betting_metrics"]["roi"] == -12.0
    assert report["simulation_metrics"]["roi_std"] > 0
    assert report["competition_codes"] == ["ENG1"]
    assert report["test_window"]["first_event"] == "2026-01-01T00:00:00+00:00"
    assert report["test_window"]["last_event"] == "2026-01-30T00:00:00+00:00"
    assert report["test_window"]["n_events"] == 15
    assert len(report["test_window"]["event_ids_sha256"]) == 64
    assert report["betting_metrics"]["coverage"] == 1.0
    assert report["betting_metrics"]["event_coverage"] == pytest.approx(10 / 15)
    assert report["betting_metrics"]["n_bet_events"] == 10


@pytest.mark.parametrize(
    ("run_status", "tags", "metrics", "trace", "codes"),
    [
        (
            "FAILED",
            {"tournament": "premier_league", "market_spec": "winner"},
            METRICS,
            TRACE,
            {"ENG1"},
        ),
        ("FINISHED", {"tournament": "nhl", "market_spec": "winner"}, METRICS, TRACE, {"ENG1"}),
        (
            "FINISHED",
            {"tournament": "premier_league", "market_spec": "winner"},
            {},
            TRACE,
            {"ENG1"},
        ),
        (
            "FINISHED",
            {"tournament": "premier_league", "market_spec": "winner"},
            METRICS,
            TRACE.iloc[:0],
            {"ENG1"},
        ),
        (
            "FINISHED",
            {"tournament": "premier_league", "market_spec": "winner"},
            METRICS,
            TRACE,
            {"ENG1", "SPA1"},
        ),
        (
            "FINISHED",
            {"tournament": "premier_league", "market_spec": "winner"},
            {**METRICS, "betting_coverage": 0.1},
            TRACE,
            {"ENG1"},
        ),
    ],
)
def test_report_rejects_unready_candidate(
    run_status: str,
    tags: dict[str, str],
    metrics: dict[str, float],
    trace: pd.DataFrame,
    codes: set[str],
) -> None:
    with pytest.raises(ValueError):
        build_tournament_candidate_report(
            CATALOG,
            "premier_league_winner",
            run_id="run-1",
            run_status=run_status,
            tags=tags,
            metrics=metrics,
            bet_trace=trace,
            competition_codes=codes,
            data_sha256="a" * 64,
            data_rows=4,
        )
