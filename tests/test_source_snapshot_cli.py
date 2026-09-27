"""CLI source acquisition для scheduler-safe snapshot."""

from pathlib import Path

from sports_forecast.orchestration import source_snapshot_cli


def test_cli_uses_tournament_and_snapshot_path(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI передаёт env contract в atomic source orchestration."""
    snapshot = tmp_path / "current.csv"
    monkeypatch.setenv("SF_CANONICAL_SOURCE_SNAPSHOT", str(snapshot))
    captured: dict[str, object] = {}

    def fake_refresh(tournament: str, current_csv: Path, *, odds_enabled: bool) -> Path:
        captured["tournament"] = tournament
        captured["current_csv"] = current_csv
        captured["odds_enabled"] = odds_enabled
        return current_csv

    monkeypatch.setattr(source_snapshot_cli, "refresh_and_publish_source_snapshot", fake_refresh)

    assert source_snapshot_cli.main(["--tournament", "nhl"]) == 0
    assert captured == {"tournament": "nhl", "current_csv": snapshot, "odds_enabled": True}
    assert str(snapshot) in capsys.readouterr().out


def test_cli_passes_explicit_odds_disabled(tmp_path: Path, monkeypatch) -> None:
    """Host runner может отключить обе odds стадии одним явным флагом."""
    monkeypatch.setenv("SF_CANONICAL_SOURCE_SNAPSHOT", str(tmp_path / "current.csv"))
    captured: list[bool] = []

    def fake_refresh(_tournament: str, _current_csv: Path, *, odds_enabled: bool) -> Path:
        captured.append(odds_enabled)
        return tmp_path / "current.csv"

    monkeypatch.setattr(source_snapshot_cli, "refresh_and_publish_source_snapshot", fake_refresh)

    assert source_snapshot_cli.main(["--tournament", "nhl", "--odds-enabled", "false"]) == 0
    assert captured == [False]
