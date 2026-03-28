"""Тесты сборки rolling-контекстов из библиотеки и sport/tournament."""

from typing import Any

import pytest

from sports_forecast.features.rolling_contexts import (
    expand_rolling_generators_inplace,
    load_rolling_context_library,
)


def test_load_library_has_team_and_h2h_team() -> None:
    order, definitions = load_rolling_context_library()
    assert "team" in order and "h2h_team" in order
    assert definitions["team"]["keys"] == ["pl", "pl_cteam"]
    assert definitions["h2h_global"]["h2h"] is True


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
