"""CLI contract canonical freshness gate."""

from __future__ import annotations

from sports_forecast.orchestration import canonical_refresh_gate_cli


def test_cli_uses_profile_and_returns_nonzero_for_failed_gate(monkeypatch) -> None:
    """Scheduler получает только безопасный status, а параметры берёт из profile."""
    captured: dict[str, object] = {}

    class Config:
        match_duration_minutes = 210
        provider_grace_minutes = 30

    class Outcome:
        passed = False
        already_finished = False

    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        canonical_refresh_gate_cli, "load_tournament_quality_gate_config", lambda _: Config()
    )
    monkeypatch.setattr(canonical_refresh_gate_cli, "get_session", lambda: SessionContext())

    def run(**kwargs: object) -> Outcome:
        captured.update(kwargs)
        return Outcome()

    monkeypatch.setattr(canonical_refresh_gate_cli, "run_canonical_freshness_gate", run)
    assert canonical_refresh_gate_cli.main(["--tournament", "nhl", "--run-id", "daily-1"]) == 1
    assert captured["match_duration_minutes"] == 210
    assert captured["provider_grace_minutes"] == 30
