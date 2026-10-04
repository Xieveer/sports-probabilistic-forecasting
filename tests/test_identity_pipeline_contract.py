"""DVC инвалидирует все identity-sensitive data stages при смене выбранного pin."""

from pathlib import Path

import pytest
import yaml


def test_dvc_stages_depend_on_identity_selection_and_local_reader() -> None:
    root = Path(__file__).resolve().parents[1]
    pipeline = yaml.safe_load((root / "dvc.yaml").read_text(encoding="utf-8"))
    identity_dependencies = {
        "sports_forecast/identity/snapshot.py",
        "sports_forecast/identity/data_provenance.py",
    }
    for stage_name in ("ingest", "clean", "features"):
        dependencies = pipeline["stages"][stage_name]["deps"]
        assert "conf/identity_registry.yaml" in dependencies
        assert "data/registry/current/" in dependencies
        assert identity_dependencies <= set(dependencies)
    assert "sports_forecast/identity/ingest.py" in pipeline["stages"]["ingest"]["deps"]
    assert "sports_forecast/identity/events.py" in pipeline["stages"]["ingest"]["deps"]


def test_rollout_selection_is_explicit_per_tournament(tmp_path: Path) -> None:
    from sports_forecast.identity.data_provenance import identity_mode_for_tournament

    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    config_path = config_dir / "identity_registry.yaml"
    config_path.write_text(
        "enabled: true\n"
        "enabled_tournaments: [nhl]\n"
        "adapters:\n  nhl:\n    source: feed\n    sport: hockey\n    row_id: id\n    event_id: event\n    scheduled_at: date\n    home_id: home\n    away_id: away\n",
        encoding="utf-8",
    )

    assert identity_mode_for_tournament(tmp_path, "nhl") is True
    assert identity_mode_for_tournament(tmp_path, "legacy_league") is False

    config_path.write_text(
        "enabled: true\nenabled_tournaments: [unsupported]\nadapters: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="adapter"):
        identity_mode_for_tournament(tmp_path, "unsupported")
