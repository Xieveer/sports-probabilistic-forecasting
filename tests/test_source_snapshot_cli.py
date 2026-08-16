"""CLI source acquisition для scheduler-safe snapshot."""

from pathlib import Path

from sports_forecast.orchestration import source_snapshot_cli


def test_cli_uses_tournament_and_snapshot_path(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI передаёт env contract в atomic source orchestration."""
    snapshot = tmp_path / "current.csv"
    monkeypatch.setenv("SF_CANONICAL_SOURCE_SNAPSHOT", str(snapshot))
    captured: dict[str, object] = {}

    def fake_refresh(tournament: str, current_csv: Path) -> Path:
        captured["tournament"] = tournament
        captured["current_csv"] = current_csv
        return current_csv

    monkeypatch.setattr(source_snapshot_cli, "refresh_and_publish_source_snapshot", fake_refresh)

    assert source_snapshot_cli.main(["--tournament", "nhl"]) == 0
    assert captured == {"tournament": "nhl", "current_csv": snapshot}
    assert str(snapshot) in capsys.readouterr().out
