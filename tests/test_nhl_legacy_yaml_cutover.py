from pathlib import Path

import pytest
import yaml

from sports_forecast.data.providers.odds import backfill, refresh, team_name_registry
from sports_forecast.identity.nhl_parity import check_nhl_registry_parity
from sports_forecast.identity.nhl_seed import import_nhl_yaml
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.snapshot import export_registry_snapshot
from sports_forecast.orchestration import live_odds_adapter
from sports_forecast.service import event_readiness, live_odds_enrichment


def test_strict_registry_does_not_open_legacy_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict runtime has no fallback dependency on the legacy NHL seed file."""

    def fail_if_opened(_path: Path):
        raise AssertionError("legacy YAML must not be opened in strict mode")

    monkeypatch.setattr(team_name_registry, "load_team_name_registry_file", fail_if_opened)

    registry = team_name_registry.load_nhl_team_name_registry(strict_mode=True)

    assert registry.is_empty
    assert registry.resolve("Colorado Avalanche") == "COLORADOAVALANCHE"


def test_parity_checker_compares_legacy_seed_master_and_snapshot(tmp_path: Path) -> None:
    seed_path = tmp_path / "nhl.yaml"
    seed_path.write_text(
        yaml.safe_dump(
            {
                "nhl_api": {"1": "Alpha Team", "2": "Beta Team"},
                "odds_api": {"Alpha Club": "Alpha Team", "Beta Club": "Beta Team"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    master_path = tmp_path / "master.sqlite3"
    registry = EntityRegistry(master_path)
    registry.initialize()
    import_nhl_yaml(registry, seed_path)
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")

    report = check_nhl_registry_parity(seed_path, master_path, snapshot.path)

    assert report.is_complete
    assert report.yaml_designations == 6
    assert report.master_snapshot_id == snapshot.snapshot_id


def test_parity_checker_reports_alias_missing_from_master(tmp_path: Path) -> None:
    seed_path = tmp_path / "nhl.yaml"
    seed = {
        "nhl_api": {"1": "Alpha Team", "2": "Beta Team"},
        "odds_api": {"Alpha Club": "Alpha Team", "Beta Club": "Beta Team"},
    }
    seed_path.write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    master_path = tmp_path / "master.sqlite3"
    registry = EntityRegistry(master_path)
    registry.initialize()
    import_nhl_yaml(registry, seed_path)
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    seed["nhl_api"]["3"] = "Alpha Team"
    seed_path.write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")

    report = check_nhl_registry_parity(seed_path, master_path, snapshot.path)

    assert not report.is_complete
    assert any(
        item.stage == "master" and item.source == "nhl_api" and item.raw_value == "3"
        for item in report.differences
    )


def test_parity_checker_requires_nhl_web_designation(tmp_path: Path) -> None:
    """Перенос source ID недостаточен без имени NHL web source для strict reader."""
    seed_path = tmp_path / "nhl.yaml"
    seed_path.write_text(
        yaml.safe_dump({"nhl_api": {"1": "Alpha Team"}, "odds_api": {"Alpha Club": "Alpha Team"}}),
        encoding="utf-8",
    )
    master_path = tmp_path / "master.sqlite3"
    registry = EntityRegistry(master_path)
    registry.initialize()
    import_nhl_yaml(registry, seed_path)
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    web_name = registry.find_designation(
        "nhl_web_api",
        "team",
        {
            "sport": "ice_hockey",
            "tournament": registry.find_designation(
                "nhl_web_api", "tournament", {"sport": "ice_hockey"}, "name", "nhl"
            ).entity_id,
        },
        "name",
        "1",
    )
    registry.decide_designation(
        web_name.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Проверка отсутствующей web связи",
        expected_revision=web_name.revision,
    )

    report = check_nhl_registry_parity(seed_path, master_path, snapshot.path)

    assert not report.is_complete
    assert any(
        item.stage == "master" and item.source == "nhl_web_api" and item.raw_value == "1"
        for item in report.differences
    )


@pytest.mark.parametrize(
    ("subject", "call"),
    [
        (backfill, lambda: backfill._resolve_team_registry("nhl", "icehockey_nhl")),
        (refresh, lambda: refresh._resolve_team_registry("nhl", "icehockey_nhl")),
    ],
)
def test_strict_odds_collection_does_not_load_legacy_yaml(
    monkeypatch: pytest.MonkeyPatch, subject, call
) -> None:
    monkeypatch.setattr(subject, "registry_event_reader_enabled", lambda: True)

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("strict odds collection attempted to load legacy YAML")

    monkeypatch.setattr(subject, "load_nhl_team_name_registry", fail_if_loaded)

    # Use the production loader contract to prove strict mode short-circuits before file I/O.
    monkeypatch.setattr(
        subject,
        "load_nhl_team_name_registry",
        lambda *, strict_mode=False: team_name_registry.TeamNameRegistry()
        if strict_mode
        else fail_if_loaded(),
    )
    assert call().is_empty


def test_strict_readiness_and_live_enrichment_do_not_load_legacy_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_readiness, "registry_event_reader_enabled", lambda: True)
    monkeypatch.setattr(live_odds_enrichment, "registry_event_reader_enabled", lambda: True)

    def strict_empty(*, strict_mode: bool = False):
        assert strict_mode
        return team_name_registry.TeamNameRegistry()

    monkeypatch.setattr(event_readiness, "load_nhl_team_name_registry", strict_empty)
    monkeypatch.setattr(live_odds_enrichment, "load_nhl_team_name_registry", strict_empty)

    assert event_readiness._participant_key("nhl", "COL") == "COL"
    assert live_odds_enrichment._registry().is_empty


def test_live_adapter_passes_strict_mode_to_registry_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omegaconf import OmegaConf

    seen = []

    def loader(*, strict_mode: bool = False):
        seen.append(strict_mode)
        assert strict_mode
        return team_name_registry.TeamNameRegistry()

    monkeypatch.setattr(
        live_odds_adapter, "load_bookmaker_config", lambda _name: OmegaConf.create({})
    )
    monkeypatch.setattr(live_odds_adapter, "registry_event_reader_enabled", lambda: True)
    monkeypatch.setattr(
        live_odds_adapter,
        "pinned_live_quote_matching",
        lambda *_args, **_kwargs: ({}, lambda _quote: None),
    )
    monkeypatch.setattr(
        live_odds_adapter,
        "fetch_nhl_pinnacle_quotes_for_refs",
        lambda _refs, **kwargs: {"registry": kwargs["team_registry"]},
    )
    monkeypatch.setitem(live_odds_adapter.TEAM_NAME_REGISTRY_LOADERS, "test", loader)

    result = live_odds_adapter.fetch_odds_api_h2h_snapshots(
        [],
        bookmaker_config="the_odds_api",
        sport_key="icehockey_nhl",
        bookmaker_key="pinnacle",
        team_registry="test",
    )

    assert result == []
    assert seen == [True]
