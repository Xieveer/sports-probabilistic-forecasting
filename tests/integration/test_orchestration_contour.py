"""Smoke/integration acceptance for orchestration: Makefile/CLI chain + DAG source contract.

These tests do **not** require a running Airflow scheduler/DB or ``apache-airflow`` in the
dev environment. DAG behaviour is checked via static parsing of ``airflow/dags/*.py`` so
CI catches regressions in the architectural contour (train → promote → materialize).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.orchestration_dag_ast import (
    DagSourceInfo,
    normalized_source_lines,
    parse_dag_source_info,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
MAIN_PY = REPO_ROOT / "main.py"
DAG_DIR = REPO_ROOT / "airflow" / "dags"

_HYDRA_HELP_OVERRIDES = (
    "tournament=uel_kz_1 market=winner market_spec=winner algorithm=catboost features=basic"
)


def _run_cli(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.integration
@pytest.mark.orchestration
def test_makefile_wires_train_promote_materialize_cli() -> None:
    """Makefile targets keep the documented Hydra / CLI entry points."""
    text = MAKEFILE.read_text(encoding="utf-8")

    def _target_block(name: str) -> str:
        m = re.search(rf"^{name}:.*?(?=^\S+:|^\Z)", text, re.MULTILINE | re.DOTALL)
        assert m is not None, f"target {name}: not found in Makefile"
        return m.group(0)

    train = _target_block("train")
    promote = _target_block("promote")
    materialize = _target_block("materialize")

    assert "python -m sports_forecast.train" in train
    assert "main.py promote compare" in promote
    assert "python -m sports_forecast.materialize" in materialize


@pytest.mark.integration
@pytest.mark.orchestration
def test_hydra_entrypoints_help_succeeds() -> None:
    """Train and materialize Hydra CLIs compose with minimal overrides (architectural wiring)."""
    train = _run_cli(["-m", "sports_forecast.train", "--help", *_HYDRA_HELP_OVERRIDES.split()])
    assert train.returncode == 0, train.stderr

    mat = _run_cli(["-m", "sports_forecast.materialize", "--help", *_HYDRA_HELP_OVERRIDES.split()])
    assert mat.returncode == 0, mat.stderr


@pytest.mark.integration
@pytest.mark.orchestration
def test_main_promote_compare_help_succeeds() -> None:
    """Unified CLI exposes promote compare (used by Makefile ``promote`` target)."""
    proc = _run_cli([str(MAIN_PY), "promote", "compare", "--help"])
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.orchestration
@pytest.mark.parametrize(
    ("filename", "expected_dag_id", "expected_tasks", "edge_substrings"),
    [
        (
            "dag_data_refresh.py",
            "data_refresh",
            ("refresh_per_tournament", "validate"),
            ("refresh_per_tournament>>validate",),
        ),
        (
            "dag_training.py",
            "training_sweep",
            ("train_sweep", "promote_best"),
            ("train_sweep>>promote",),
        ),
        (
            "dag_monitoring.py",
            "model_monitoring",
            (
                "check_data_freshness",
                "check_model_quality",
                "decide_retrain",
                "trigger_retrain",
                "skip_retrain",
            ),
            (
                "check_data_freshness>>check_model_quality>>decide",
                "decide>>[trigger_retrain,skip_retrain]",
            ),
        ),
        (
            "dag_nhl_morning_refresh.py",
            "nhl_morning_refresh",
            ("refresh_nhl_morning", "validate", "post_refresh_digest"),
            ("refresh_nhl>>validate>>post_refresh_digest",),
        ),
    ],
)
def test_dag_source_contract(
    filename: str,
    expected_dag_id: str,
    expected_tasks: tuple[str, ...],
    edge_substrings: tuple[str, ...],
) -> None:
    """DAG modules keep ``dag_id``, tasks, and documented dependencies (source-level)."""
    path = DAG_DIR / filename
    assert path.is_file(), f"missing {path}"

    info = parse_dag_source_info(path)
    assert info.dag_id == expected_dag_id
    assert set(info.task_ids) == set(expected_tasks), (
        f"{filename}: task_ids {set(info.task_ids)} != expected {set(expected_tasks)}"
    )

    compact = normalized_source_lines(path)
    for frag in edge_substrings:
        assert frag in compact, f"{filename}: expected `{frag}` in normalized source"

    if filename == "dag_nhl_morning_refresh.py":
        text_cmd = path.read_text(encoding="utf-8")
        assert "bash_post_refresh_digest" in text_cmd
        bash_digest = (
            REPO_ROOT / "sports_forecast" / "orchestration" / "airflow_post_refresh_digest_bash.py"
        )
        assert bash_digest.is_file()
        digest_src = bash_digest.read_text(encoding="utf-8")
        assert "sports_forecast.orchestration.post_refresh_digest" in digest_src
        assert "var.value.get('SF_TELEGRAM_DIGEST_ENABLE', 'true')" in digest_src

    _assert_dag_cli_contract(filename, path, info)


@pytest.mark.integration
@pytest.mark.orchestration
def test_dag_materialize_source_contract() -> None:
    """Materialize DAG uses dynamic ``task_id`` (f-string); check pattern and CLI wiring."""
    path = DAG_DIR / "dag_materialize.py"
    info = parse_dag_source_info(path)
    assert info.dag_id == "prediction_materialize"
    assert info.task_ids == (), "task_ids are f-string-based; see body assertions below"

    text = path.read_text(encoding="utf-8")
    compact = normalized_source_lines(path)
    assert 'task_id=f"materialize_{tournament}"' in text
    assert "sports_forecast.materialize" in text
    assert "prev_task>>task" in compact

    default_tournaments_csv = "uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by"
    assert default_tournaments_csv in text, (
        "SF_MATERIALIZE_TOURNAMENTS default_var must list tournaments"
    )

    _assert_dag_cli_contract("dag_materialize.py", path, info)


def _assert_dag_cli_contract(filename: str, path: Path, info: DagSourceInfo) -> None:
    """Cross-check that DAG sources invoke the same CLI modules as the Makefile chain."""
    text = path.read_text(encoding="utf-8")
    if filename == "dag_training.py":
        assert "sports_forecast.train" in text
        assert "build_promote_per_tournament_command" in text
    if filename == "dag_materialize.py":
        assert "sports_forecast.materialize" in text
    if filename == "dag_data_refresh.py":
        assert "build_refresh_per_tournament_command" in text
        assert "sports_forecast.validation.run_validation" in text
    if filename == "dag_monitoring.py":
        assert "check_data_freshness" in info.task_ids
    if filename == "dag_nhl_morning_refresh.py":
        assert "bash_refresh_per_tournament" in text
        assert "sf_scheduled_refresh_ops" in text
        ops_mod = DAG_DIR / "sf_scheduled_refresh_ops.py"
        ops_text = ops_mod.read_text(encoding="utf-8")
        assert "build_refresh_per_tournament_command" in ops_text
        assert "sports_forecast.validation.run_validation" in ops_text
        bash_digest = (
            REPO_ROOT / "sports_forecast" / "orchestration" / "airflow_post_refresh_digest_bash.py"
        )
        digest_src = bash_digest.read_text(encoding="utf-8")
        assert "sports_forecast.orchestration.post_refresh_digest" in digest_src
