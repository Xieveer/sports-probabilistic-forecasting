from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest

from sports_forecast.research import oos_predictions
from sports_forecast.research.oos_predictions import (
    _read_raw_rows_before_cutoff,
    _universe_rows_by_source,
    _winner_with_ot_target,
    build_oos_predictions,
    load_verified_input,
    write_oos_predictions,
)


_FINGERPRINTS = dict.fromkeys(
    (
        "matches_sha256",
        "team_seed_sha256",
        "universe_sha256",
        "provider_dataset_sha256",
        "provider_events_sha256",
    ),
    "sha256:" + "0" * 64,
)


def _events() -> pd.DataFrame:
    rows = []
    for i, date in enumerate(pd.date_range("2024-07-01", "2024-09-20", freq="5D", tz="UTC")):
        rows.append(
            {
                "project_event_id": f"event-{i}",
                "source_event_id": str(1000 + i),
                "kickoff_utc": date.isoformat(),
                "home_team": "BOS" if i % 2 else "NYR",
                "away_team": "NYR" if i % 2 else "BOS",
                "status": "finished",
                "home_score_ft": 3 if i % 2 else 1,
                "away_score_ft": 1 if i % 2 else 2,
                "dataset_eligible": True,
            }
        )
    rows.extend(
        [
            {
                "project_event_id": "event-proxy-boundary",
                "source_event_id": "8999",
                "kickoff_utc": "2024-09-17T00:00:00Z",
                "home_team": "BOS",
                "away_team": "NYR",
                "status": "finished",
                "home_score_ft": 2,
                "away_score_ft": 1,
                "dataset_eligible": True,
            },
            {
                "project_event_id": "event-proxy-after-boundary",
                "source_event_id": "8998",
                "kickoff_utc": "2024-09-25T00:00:00Z",
                "home_team": "NYR",
                "away_team": "BOS",
                "status": "finished",
                "home_score_ft": 2,
                "away_score_ft": 1,
                "dataset_eligible": True,
            },
            {
                "project_event_id": "event-vocabulary-boundary",
                "source_event_id": "8997",
                "kickoff_utc": "2024-09-24T00:00:00Z",
                "home_team": "SEA",
                "away_team": "NYR",
                "status": "finished",
                "home_score_ft": 2,
                "away_score_ft": 1,
                "dataset_eligible": True,
            },
            {
                "project_event_id": "event-dev-too-recent",
                "source_event_id": "9001",
                "kickoff_utc": "2024-09-28T00:00:00Z",
                "home_team": "BOS",
                "away_team": "NYR",
                "status": "finished",
                "home_score_ft": 2,
                "away_score_ft": 1,
                "dataset_eligible": True,
            },
            {
                "project_event_id": "event-oos",
                "source_event_id": "9002",
                "kickoff_utc": "2024-10-08T00:00:00Z",
                "home_team": "NEW",
                "away_team": "NYR",
                "status": "finished",
                "home_score_ft": 4,
                "away_score_ft": 2,
                "dataset_eligible": True,
            },
        ]
    )
    return pd.DataFrame(rows)


def test_monthly_prediction_uses_same_proxy_eligible_rows_and_unknown_team() -> None:
    result = build_oos_predictions(
        _events(),
        dataset_id="pd1:" + "1" * 64,
        registry_snapshot_id="ir1:" + "2" * 64,
        source_fingerprints=_FINGERPRINTS,
        confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
        start="2024-10-01T00:00:00Z",
        end="2024-11-01T00:00:00Z",
    )

    assert len(result.predictions) == 2
    candidate, baseline = result.predictions
    assert candidate["project_event_id"] == baseline["project_event_id"] == "event-oos"
    training_step = result.manifest["training_steps"][0]
    assert candidate["train_source_ids_sha256"] == baseline["train_source_ids_sha256"]
    assert "9001" not in training_step["train_source_ids"]
    assert "8997" in training_step["train_source_ids"]
    assert "8998" not in training_step["train_source_ids"]
    assert candidate["features"]["home_team"] == "NEW"
    assert "NEW" not in result.manifest["team_feature_vocabulary"]
    assert "SEA" in result.manifest["team_feature_vocabulary"]
    assert not any(key.startswith("home_team_NEW") for key in candidate["feature_values"])
    assert candidate["probabilities"]["home_win"] + candidate["probabilities"][
        "away_win"
    ] == pytest.approx(1.0)
    assert candidate["feature_hash"].startswith("sha256:")
    assert "home_score_ft" not in candidate
    assert "y_true" not in candidate
    assert candidate["training_cutoff_utc"] == "2024-10-01T00:00:00Z"
    assert candidate["kickoff_cutoff_utc"] == "2024-09-24T00:00:00Z"
    assert candidate["decision_at"] == "2024-10-07T23:45:00Z"
    assert result.manifest["dataset_id"] == "pd1:" + "1" * 64
    repeated = build_oos_predictions(
        _events(),
        dataset_id="pd1:" + "1" * 64,
        registry_snapshot_id="ir1:" + "2" * 64,
        source_fingerprints=_FINGERPRINTS,
        confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
        start="2024-10-01T00:00:00Z",
        end="2024-11-01T00:00:00Z",
    )
    assert result.manifest["prediction_id"] == repeated.manifest["prediction_id"]
    assert result.predictions == repeated.predictions


def test_prediction_artifacts_are_byte_identical_on_repeat(tmp_path: Path) -> None:
    result = build_oos_predictions(
        _events(),
        dataset_id="pd1:" + "1" * 64,
        registry_snapshot_id="ir1:" + "2" * 64,
        source_fingerprints=_FINGERPRINTS,
        confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
        start="2024-10-01T00:00:00Z",
        end="2024-11-01T00:00:00Z",
    )
    first = write_oos_predictions(result, tmp_path)
    original = tuple(path.read_bytes() for path in first)
    second = write_oos_predictions(result, tmp_path)
    assert first == second
    assert tuple(path.read_bytes() for path in second) == original
    assert "generated_at_utc" not in result.manifest


def test_winner_with_ot_target_uses_home_orientation_and_rejects_ties() -> None:
    home = pd.Series({"status": "finished", "home_score_ft": "4", "away_score_ft": "3"})
    reverse = pd.Series({"status": "finished", "home_score_ft": "3", "away_score_ft": "4"})
    tie = pd.Series({"status": "finished", "home_score_ft": "3", "away_score_ft": "3"})
    unfinished = pd.Series({"status": "scheduled", "home_score_ft": "4", "away_score_ft": "3"})

    assert _winner_with_ot_target(home) == 1
    assert _winner_with_ot_target(reverse) == 0
    assert _winner_with_ot_target(tie) is None
    assert _winner_with_ot_target(unfinished) is None


@pytest.mark.parametrize("home_score,away_score", [(-1, 0), (1.5, 0), (float("inf"), 1), (2, 2)])
def test_winner_with_ot_target_rejects_invalid_finished_scores(
    home_score: float,
    away_score: float,
) -> None:
    row = pd.Series(
        {
            "status": "finished",
            "home_score_ft": home_score,
            "away_score_ft": away_score,
        }
    )

    assert _winner_with_ot_target(row) is None


def test_raw_loader_pushes_cutoff_before_projecting_status_and_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyarrow.dataset as ds

    identity = pd.DataFrame(
        {
            "id": ["dev", "locked"],
            "nhl_id": ["dev", "locked"],
            "datetime": ["2024-09-30T23:00:00Z", "2024-10-01T00:00:00Z"],
            "home_team": ["BOS", "NYR"],
            "away_team": ["NYR", "BOS"],
            "game_type": ["regular", "regular"],
        }
    )
    calls: dict[str, object] = {}
    outcome_rows = pd.DataFrame(
        {
            "id": ["dev"],
            "match_is_end": ["1"],
            "home_score_ft": [3],
            "away_score_ft": [2],
        }
    )

    def read_identity(_path: Path, *, columns: list[str]) -> pd.DataFrame:
        calls["identity_columns"] = columns
        return identity[columns].copy()

    class Dataset:
        def to_table(self, *, columns: list[str], filter: object) -> object:
            calls["outcome_columns"] = columns
            calls["filter"] = filter
            table = outcome_rows[columns]
            return type("Table", (), {"to_pandas": lambda self: table})()

    monkeypatch.setattr(pd, "read_parquet", read_identity)
    monkeypatch.setattr(ds, "dataset", lambda _path, format: Dataset())

    result = _read_raw_rows_before_cutoff(Path("synthetic.parquet"), "2024-10-01T00:00:00Z")

    assert result["id"].tolist() == ["dev"]
    identity_columns = cast(list[str], calls["identity_columns"])
    assert "home_score_ft" not in identity_columns
    assert "match_is_end" not in identity_columns
    assert calls["outcome_columns"] == ["id", "match_is_end", "home_score_ft", "away_score_ft"]
    assert calls["filter"] is not None
    assert "2024-10-01T00:00:00Z" in str(calls["filter"])

    outcome_rows.loc[len(outcome_rows)] = ["locked", "1", 8, 1]
    with pytest.raises(ValueError, match="outside the date cutoff"):
        _read_raw_rows_before_cutoff(Path("synthetic.parquet"), "2024-10-01T00:00:00Z")

    outcome_rows.drop(index=1, inplace=True)
    outcome_rows.drop(index=0, inplace=True)
    with pytest.raises(ValueError, match="exactly cover"):
        _read_raw_rows_before_cutoff(Path("synthetic.parquet"), "2024-10-01T00:00:00Z")


def test_universe_partition_keeps_timed_unknown_team_diagnostic() -> None:
    universe = {
        "nhl_events": [
            {
                "row_id": "known",
                "source_event_id": "known",
                "kickoff_utc": "2023-10-01T00:00:00.000000Z",
                "project_event_id": "uuid-known",
                "status": "resolved",
            }
        ],
        "nhl_diagnostics": [
            {
                "row_id": "unknown",
                "source_event_id": "unknown",
                "kickoff_utc": "2023-10-02T00:00:00.000000Z",
                "project_event_id": None,
                "status": "unresolved",
            }
        ],
    }
    expected = [
        (("known", "known", "2023-10-01T00:00:00.000000Z"), "uuid-known"),
        (("unknown", "unknown", "2023-10-02T00:00:00.000000Z"), None),
    ]

    by_source = _universe_rows_by_source(universe, expected)

    assert by_source["known"]["project_event_id"] == "uuid-known"
    assert by_source["unknown"]["project_event_id"] is None


def test_universe_window_projection_uses_half_open_pd1_boundaries() -> None:
    universe = {
        "window": {
            "start_utc": "2023-10-01T00:00:00Z",
            "end_utc_exclusive": "2026-05-01T00:00:00Z",
        },
        "nhl_events": [
            {"source_event_id": "before", "kickoff_utc": "2024-09-30T23:59:59Z"},
            {"source_event_id": "start", "kickoff_utc": "2024-10-01T00:00:00Z"},
            {"source_event_id": "end", "kickoff_utc": "2026-05-01T00:00:00Z"},
        ],
        "nhl_diagnostics": [],
    }

    projected = oos_predictions._universe_projection_for_window(
        universe,
        pd.Timestamp("2024-10-01T00:00:00Z"),
        pd.Timestamp("2026-05-01T00:00:00Z"),
    )

    assert [row["source_event_id"] for row in projected["nhl_events"]] == ["start"]
    with pytest.raises(ValueError, match="подмножеством"):
        oos_predictions._universe_projection_for_window(
            universe,
            pd.Timestamp("2023-09-30T00:00:00Z"),
            pd.Timestamp("2024-10-01T00:00:00Z"),
        )


def test_verified_input_projects_full_ir1_universe_to_pd1_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches_path = tmp_path / "matches.parquet"
    matches_path.write_bytes(b"synthetic raw fingerprint")
    team_seed_path = tmp_path / "team-seed.yaml"
    team_seed_path.write_text("nhl_api:\n  boston: BOS\n  new_york: NYR\n", encoding="utf-8")
    history_path = tmp_path / "history.sqlite3"
    history_path.write_bytes(b"synthetic history")
    snapshot_path = tmp_path / "snapshot"
    snapshot_path.write_text("synthetic snapshot", encoding="utf-8")

    full_start, pd1_start, pd1_end, full_end = (
        "2023-10-01T00:00:00Z",
        "2024-10-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
    )
    universe_rows = [
        {
            "row_id": "dev-row",
            "source_event_id": "dev",
            "kickoff_utc": "2023-10-02T00:00:00.000000Z",
            "project_event_id": "uuid-dev",
            "status": "resolved",
        },
        {
            "row_id": "locked-row",
            "source_event_id": "locked",
            "kickoff_utc": "2024-10-02T00:00:00.000000Z",
            "project_event_id": "uuid-locked",
            "status": "resolved",
        },
    ]
    universe = {
        "format": "sports-forecast-pinned-nhl-universe",
        "format_version": 1,
        "run_id": "irun-test",
        "snapshot_id": "ir1:" + "a" * 64,
        "window": {"start_utc": full_start, "end_utc_exclusive": full_end},
        "source_fingerprints": {
            "matches_sha256": oos_predictions._sha256_file(matches_path),
            "team_seed_sha256": oos_predictions._sha256_file(team_seed_path),
        },
        "expected_events": len(universe_rows),
        "nhl_events": universe_rows,
        "nhl_diagnostics": [],
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe, sort_keys=True), encoding="utf-8")
    pd1_row = {
        "source_event_id": "locked",
        "project_event_id": "uuid-locked",
        "kickoff_utc": "2024-10-02T00:00:00.000000Z",
        "coverage": "covered",
    }
    events_path = tmp_path / "events.jsonl"
    events_path.write_bytes(oos_predictions._canonical_bytes(pd1_row) + b"\n")
    core = {
        "format": "sports-forecast-provider-asof-dataset",
        "format_version": 1,
        "registry_snapshot_id": universe["snapshot_id"],
        "universe_run_id": universe["run_id"],
        "universe_sha256": oos_predictions._sha256_file(universe_path),
        "historical_fingerprint": "sha256:" + "b" * 64,
        "resolved_config": {
            "source": "the_odds_api",
            "bookmaker": "pinnacle",
            "market": "winner_withOT",
            "selection_mode": "provider_as_of",
            "window_start_utc": pd1_start,
            "window_end_utc_exclusive": pd1_end,
        },
        "events_sha256": oos_predictions._sha256_file(events_path),
        "expected_events": 1,
        "coverage": {"covered": 1},
        "retrieval_diagnostics": {"unknown": 0, "late": 0},
    }
    provider_manifest = {
        **core,
        "dataset_id": "pd1:" + hashlib.sha256(oos_predictions._canonical_bytes(core)).hexdigest(),
    }
    provider_path = tmp_path / "manifest.json"
    provider_path.write_text(json.dumps(provider_manifest, sort_keys=True), encoding="utf-8")

    calls: list[tuple[str, str]] = []
    raw_identity: list[dict[str, Any]] = [
        {
            "row_id": "dev-row",
            "source_event_id": "dev",
            "kickoff": pd.Timestamp(universe_rows[0]["kickoff_utc"]),
            "home": "BOS",
            "away": "NYR",
        },
        {
            "row_id": "locked-row",
            "source_event_id": "locked",
            "kickoff": pd.Timestamp(universe_rows[1]["kickoff_utc"]),
            "home": "BOS",
            "away": "NYR",
        },
    ]

    def read_matches(
        _path: Path, start: pd.Timestamp, end: pd.Timestamp
    ) -> tuple[list[dict], None, None]:
        calls.append((start.isoformat(), end.isoformat()))
        selected = [row for row in raw_identity if start <= row["kickoff"] < end]
        return selected, None, None

    def expected_partition(
        rows: list[dict], _registry: object
    ) -> list[tuple[tuple[str, str, str], str]]:
        return [
            (
                (
                    row["row_id"],
                    row["source_event_id"],
                    row["kickoff"].isoformat(timespec="microseconds").replace("+00:00", "Z"),
                ),
                "uuid-" + row["source_event_id"],
            )
            for row in rows
        ]

    class FakeRegistry:
        snapshot = SimpleNamespace(
            event_snapshot=SimpleNamespace(
                events=[
                    SimpleNamespace(sport="ice_hockey", tournament_id="nhl-tournament"),
                ]
            )
        )

        @staticmethod
        def get_entity(_entity_id: str) -> SimpleNamespace:
            return SimpleNamespace(project_name="NHL")

        @staticmethod
        def resolve_designation(**_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status="resolved")

    monkeypatch.setattr(
        oos_predictions,
        "verify_registry_snapshot",
        lambda _path: SimpleNamespace(snapshot_id=universe["snapshot_id"]),
    )
    monkeypatch.setattr(oos_predictions, "RegistrySnapshotReader", lambda _snapshot: FakeRegistry())
    monkeypatch.setattr(oos_predictions, "_read_matches", read_matches)
    monkeypatch.setattr(oos_predictions, "_expected_nhl_partition", expected_partition)
    monkeypatch.setattr(
        oos_predictions, "_historical_fingerprint", lambda _path: core["historical_fingerprint"]
    )
    monkeypatch.setattr(
        oos_predictions,
        "_read_raw_rows_before_cutoff",
        lambda _path, _end: pd.DataFrame(
            [
                {
                    "id": "raw-locked",
                    "nhl_id": "locked",
                    "datetime": "2024-10-02T00:00:00Z",
                    "home_team": "BOS",
                    "away_team": "NYR",
                    "game_type": "regular",
                    "match_is_end": "1",
                    "home_score_ft": 2,
                    "away_score_ft": 1,
                }
            ]
        ),
    )

    events, _, dataset_id, snapshot_id, _ = load_verified_input(
        matches_path=matches_path,
        team_seed_path=team_seed_path,
        universe_path=universe_path,
        provider_manifest_path=provider_path,
        snapshot_path=snapshot_path,
        historical_database_path=history_path,
        end=pd1_end,
    )

    assert calls == [(pd.Timestamp(pd1_start).isoformat(), pd.Timestamp(pd1_end).isoformat())]
    assert dataset_id == provider_manifest["dataset_id"]
    assert snapshot_id == universe["snapshot_id"]
    assert events["source_event_id"].tolist() == ["locked"]
    assert events["project_event_id"].tolist() == ["uuid-locked"]
    assert events["dataset_eligible"].tolist() == [True]


def test_unknown_team_diagnostic_is_explicitly_excluded() -> None:
    events = _events()
    events["team_identity_eligible"] = True
    events.loc[len(events)] = {
        "project_event_id": None,
        "source_event_id": "unresolved-unknown-team",
        "kickoff_utc": "2024-10-12T00:00:00Z",
        "home_team": "MYSTERY",
        "away_team": "NYR",
        "status": "finished",
        "home_score_ft": 2,
        "away_score_ft": 1,
        "dataset_eligible": False,
        "team_identity_eligible": False,
    }

    result = build_oos_predictions(
        events,
        dataset_id="pd1:" + "1" * 64,
        registry_snapshot_id="ir1:" + "2" * 64,
        source_fingerprints=_FINGERPRINTS,
        confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
        start="2024-10-01T00:00:00Z",
        end="2024-11-01T00:00:00Z",
    )

    assert result.manifest["exclusions"]["unconfirmed_team_identity"] == 1
    assert all(
        prediction["source_event_id"] != "unresolved-unknown-team"
        for prediction in result.predictions
    )


def test_reverse_mapping_duplicate_and_bad_labels_are_rejected() -> None:
    events = _events()
    duplicate = pd.concat([events, events.iloc[[-1]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_oos_predictions(
            duplicate,
            dataset_id="pd1:" + "1" * 64,
            registry_snapshot_id="ir1:" + "2" * 64,
            source_fingerprints=_FINGERPRINTS,
            confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
            start="2024-10-01T00:00:00Z",
            end="2024-11-01T00:00:00Z",
        )


def test_unapproved_feature_columns_are_rejected() -> None:
    events = _events()
    events["f_leak"] = 0.0
    with pytest.raises(ValueError, match="unexpected columns"):
        build_oos_predictions(
            events,
            dataset_id="pd1:" + "1" * 64,
            registry_snapshot_id="ir1:" + "2" * 64,
            source_fingerprints=_FINGERPRINTS,
            confirmed_team_codes={"BOS", "NYR", "NEW", "SEA"},
            start="2024-10-01T00:00:00Z",
            end="2024-11-01T00:00:00Z",
        )
