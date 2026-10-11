import json
from datetime import date
from types import SimpleNamespace

import pytest

from sports_forecast.data.providers.nhl.schedule import ScheduleGameStub
from sports_forecast.identity import nhl_event_bootstrap_cli
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.review_service import ReviewQueueService


def _game(home="FAKE"):
    return ScheduleGameStub(
        game_id=2026020001,
        season=20262027,
        game_type=2,
        game_date="2026-10-10",
        start_time_utc="2026-10-10T23:00:00Z",
        venue_default="",
        home_abbrev=home,
        away_abbrev="BUF",
        game_state="FUT",
        match_end=None,
        home_score=None,
        away_score=None,
    )


def _registry(path):
    registry = EntityRegistry(path)
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    registry.add_designation(
        entity_id=tournament.id,
        source="nhl_web_api",
        kind="tournament",
        scope={"sport": "ice_hockey"},
        value_kind="name",
        raw_value="nhl",
        state="confirmed",
    )
    away = registry.create_entity("team", "Buffalo Sabres", sport="ice_hockey")
    registry.add_designation(
        entity_id=away.id,
        source="nhl_web_api",
        kind="team",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="name",
        raw_value="BUF",
        state="confirmed",
    )
    return registry


def _mock_network(monkeypatch, games):
    calls = []

    class FakeClient:
        def __init__(self, config):
            calls.append(("client", config))

    monkeypatch.setattr(nhl_event_bootstrap_cli, "NhlApiClient", FakeClient)
    monkeypatch.setattr(
        nhl_event_bootstrap_cli.OmegaConf, "load", lambda _path: SimpleNamespace(provider={})
    )

    def fetch_schedule_day(client, anchor):
        calls.append(("fetch", anchor))
        return games

    monkeypatch.setattr(nhl_event_bootstrap_cli, "fetch_schedule_day", fetch_schedule_day)
    return calls


def test_cli_defaults_to_dry_run_and_reports_review_summary(tmp_path, monkeypatch, capsys):
    master = tmp_path / "master.sqlite3"
    _registry(master)
    calls = _mock_network(monkeypatch, [_game()])

    exit_code = nhl_event_bootstrap_cli.main(["--master", str(master), "--anchor", "2026-10-11"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls[-1] == ("fetch", date(2026, 10, 11))
    assert output["dry_run"] is True
    assert output["counts_by_status"] == {"needs_review": 1}
    assert output["counts_by_reason"] == {"designation_not_uniquely_confirmed": 1}
    assert "snapshot" not in output
    assert EntityRegistry(master).list_entities(kind="event") == []


def test_cli_apply_persists_review_candidate_and_reports_it(tmp_path, monkeypatch, capsys):
    master = tmp_path / "master.sqlite3"
    _registry(master)
    _mock_network(monkeypatch, [_game()])

    exit_code = nhl_event_bootstrap_cli.main(
        ["--master", str(master), "--anchor", "2026-10-11", "--apply"]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dry_run"] is False
    assert output["counts_by_status"] == {"needs_review": 1}
    assert output["counts_by_reason"] == {"designation_not_uniquely_confirmed": 1}
    assert EntityRegistry(master).list_entities(kind="event") == []
    assert ReviewQueueService(EntityRegistry(master)).list_candidates(
        source="nhl_web_api", query="2026020001"
    )


def test_cli_rejects_invalid_anchor_date(tmp_path, monkeypatch):
    _mock_network(monkeypatch, [])

    with pytest.raises(SystemExit, match="2"):
        nhl_event_bootstrap_cli.main(
            ["--master", str(tmp_path / "master.sqlite3"), "--anchor", "2026-02-30"]
        )
