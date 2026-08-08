"""Контракт безопасного dry-run NHL readiness CLI."""

from __future__ import annotations

import json
from pathlib import Path

from sports_forecast.orchestration import nhl_readiness


def test_dry_run_emits_safe_plan_without_external_calls(capsys) -> None:
    """Dry-run описывает порядок шагов, не раскрывая env и не обращаясь к провайдерам."""
    assert nhl_readiness.main(["--dry-run"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "dry_run"
    assert plan["tournament"] == "nhl"
    assert plan["steps"] == ["source_refresh", "quality_gate", "odds_refresh", "materialize"]
    assert "api_key" not in json.dumps(plan).lower()


def test_execute_without_upcoming_schedule_skips_gate_and_odds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Межсезонье — штатный статус, не повод вызывать quality gate или Odds API."""
    source_csv = tmp_path / "source.csv"
    source_csv.write_text("datetime,match_is_end\n2026-06-10T00:00:00Z,1\n", encoding="utf-8")
    monkeypatch.setattr(nhl_readiness, "refresh_source", lambda *_args, **_kwargs: source_csv)
    monkeypatch.setattr(
        nhl_readiness, "quality_gate_main", lambda *_args: (_ for _ in ()).throw(AssertionError())
    )
    monkeypatch.setattr(
        nhl_readiness, "run_odds_refresh", lambda **_kwargs: (_ for _ in ()).throw(AssertionError())
    )

    assert nhl_readiness.main(["--execute"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_upcoming_schedule"
