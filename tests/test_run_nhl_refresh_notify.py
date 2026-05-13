"""Тесты для ``scripts/run_nhl_refresh_notify.py`` (R39.8 digest CLI)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_nhl_refresh_notify.py"


def _load_notify_module():
    spec = importlib.util.spec_from_file_location("run_nhl_refresh_notify", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def notify_mod():
    return _load_notify_module()


def test_skip_telegram_skip_pipeline_runs_digest_dry_run(notify_mod) -> None:
    """Самый быстрый путь: без пайплайна — один вызов post_refresh_digest с --dry-run."""
    with patch.object(notify_mod.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="digest text\n", stderr="")
        argv = [
            "run_nhl_refresh_notify.py",
            "--delay-seconds",
            "0",
            "--skip-telegram",
            "--skip-pipeline",
        ]
        with patch.object(sys, "argv", argv):
            rc = notify_mod.main()
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == sys.executable
        assert cmd[1:3] == ["-m", "sports_forecast.orchestration.post_refresh_digest"]
        assert "--project-root" in cmd
        assert str(notify_mod.PROJECT_ROOT) in cmd
        assert "--tournament" in cmd
        assert "nhl" in cmd
        assert "--market" in cmd
        assert "winner_withOT" in cmd
        assert "--market-spec" in cmd
        assert cmd[-1] == "--dry-run"
        assert kwargs.get("cwd") == notify_mod.PROJECT_ROOT
        assert kwargs.get("check") is False
        assert kwargs.get("capture_output") is True
        assert rc == 0
