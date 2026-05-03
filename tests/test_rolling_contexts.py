"""Тесты сборки rolling-контекстов из библиотеки и sport/tournament."""

from typing import Any

import pytest

from sports_forecast.features.rolling_contexts import (
    _load_column_aliases,
    _resolve_keys,
    expand_rolling_generators_inplace,
    load_rolling_context_library,
)


def test_load_library_has_team_and_h2h_team() -> None:
    order, definitions = load_rolling_context_library()
    assert "team" in order and "h2h_team" in order
    assert definitions["team"]["keys"] == ["pl", "pl_cteam"]
    assert definitions["h2h_global"]["h2h"] is True


def test_inseason_context_loaded() -> None:
    _, definitions = load_rolling_context_library()
    assert "inseason" in definitions
    assert definitions["inseason"]["keys"] == ["pl", "season"]
    assert definitions["inseason"]["players"] == ["pl", "opp"]
    assert "h2h_inseason" in definitions
    assert definitions["h2h_inseason"]["keys"] == ["pl", "opp", "season"]
    assert definitions["h2h_inseason"]["h2h"] is True


def test_resolve_keys_no_aliases() -> None:
    assert _resolve_keys(["pl", "season"], {}) == ["pl", "season"]


def test_resolve_keys_with_aliases() -> None:
    aliases = {"season": "season_id", "weekday": "dow"}
    assert _resolve_keys(["pl", "season"], aliases) == ["pl", "season_id"]
    assert _resolve_keys(["pl", "weekday"], aliases) == ["pl", "dow"]


def test_resolve_keys_partial_aliases() -> None:
    aliases = {"season": "season_id"}
    assert _resolve_keys(["pl", "season", "opp"], aliases) == ["pl", "season_id", "opp"]


def test_load_column_aliases_empty() -> None:
    assert _load_column_aliases(None) == {}
    assert _load_column_aliases({}) == {}
    assert _load_column_aliases({"rolling_context_names": []}) == {}


def test_expand_table_tennis_excludes_console_team_contexts() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "ewm_diff": {"type": "ewm", "context_source": "library"},
            "ewm_total": {"type": "ewm", "context_source": "library"},
            "count": {"type": "count", "context_source": "library"},
        }
    }
    tournament_cfg = {
        "rolling_context_names": [
            "global",
            "h2h_global",
            # без team / h2h_team
        ]
    }
    expand_rolling_generators_inplace(features_cfg, tournament_cfg)

    names = [c["name"] for c in features_cfg["generators"]["ewm_diff"]["contexts"]]
    assert "team" not in names and "h2h_team" not in names
    assert names == ["global", "h2h_global"]

    diff_global = next(
        c for c in features_cfg["generators"]["ewm_diff"]["contexts"] if c["name"] == "global"
    )
    assert diff_global["compute_diff"] is True

    total_global = next(
        c for c in features_cfg["generators"]["ewm_total"]["contexts"] if c["name"] == "global"
    )
    assert total_global["compute_diff"] is False

    count_global = next(
        c for c in features_cfg["generators"]["count"]["contexts"] if c["name"] == "global"
    )
    assert "compute_diff" not in count_global


def test_expand_full_set_when_no_rolling_names() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "count": {"type": "count", "context_source": "library"},
        }
    }
    expand_rolling_generators_inplace(features_cfg, tournament_cfg=None)
    _, definitions = load_rolling_context_library()
    assert len(features_cfg["generators"]["count"]["contexts"]) == len(definitions)


def test_unknown_context_raises() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "count": {"type": "count", "context_source": "library"},
        }
    }
    with pytest.raises(ValueError, match="неизвестные"):
        expand_rolling_generators_inplace(
            features_cfg,
            tournament_cfg={"rolling_context_names": ["global", "not_a_real_context"]},
        )


def test_expand_with_aliases() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "ewm_diff": {"type": "ewm", "context_source": "library"},
            "count": {"type": "count", "context_source": "library"},
        }
    }
    tournament_cfg = {
        "rolling_context_names": ["global", "inseason"],
        "rolling_column_aliases": {"season": "season_id"},
    }
    expand_rolling_generators_inplace(features_cfg, tournament_cfg)

    ins = next(
        c for c in features_cfg["generators"]["ewm_diff"]["contexts"] if c["name"] == "inseason"
    )
    assert ins["keys"] == ["pl", "season_id"]

    ins_c = next(
        c for c in features_cfg["generators"]["count"]["contexts"] if c["name"] == "inseason"
    )
    assert ins_c["keys"] == ["pl", "season_id"]


def test_expand_without_aliases_backward_compat() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "ewm_diff": {"type": "ewm", "context_source": "library"},
        }
    }
    tournament_cfg = {"rolling_context_names": ["global", "inseason"]}
    expand_rolling_generators_inplace(features_cfg, tournament_cfg)
    ins = next(
        c for c in features_cfg["generators"]["ewm_diff"]["contexts"] if c["name"] == "inseason"
    )
    assert ins["keys"] == ["pl", "season"]


def test_expand_library_unknown_type_raises() -> None:
    features_cfg: dict[str, Any] = {
        "generators": {
            "bad": {"type": "noop", "context_source": "library"},
        }
    }
    with pytest.raises(ValueError, match="library requires"):
        expand_rolling_generators_inplace(
            features_cfg,
            tournament_cfg={"rolling_context_names": ["global"]},
        )
