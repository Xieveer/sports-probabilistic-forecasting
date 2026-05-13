"""Быстрые тесты CLI ``post_refresh_digest`` (R39.4)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sports_forecast.orchestration import post_refresh_digest as prd
from sports_forecast.service.db.models import Prediction


@pytest.fixture
def deploy_tree(tmp_path):
    """Минимальный ``models/<tournament>/<spec>/best/deploy.yaml``."""
    p = tmp_path / "models" / "nhl" / "winner_withOT" / "best" / "deploy.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(
        "model:\n  run_name: smoke-run\n  algorithm: catboost\n",
        encoding="utf-8",
    )
    return tmp_path


def _sample_prediction() -> Prediction:
    return Prediction(
        id=1,
        match_id="m1",
        tournament="nhl",
        market="winner_withOT",
        market_spec="winner_withOT",
        home_player="Home",
        away_player="Away",
        match_datetime=datetime(2026, 5, 13, 12, 0, 0),
        model_version="mv",
        algorithm="catboost",
        featureset="advanced",
        predictions_json='{"home_win":0.55,"away_win":0.45}',
        status="ok",
    )


def test_digest_disabled_skips_without_touching_engine(monkeypatch) -> None:
    monkeypatch.setenv("SF_TELEGRAM_DIGEST_ENABLE", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _should_not_run() -> None:
        raise AssertionError("get_engine must not be called when digest is disabled")

    monkeypatch.setattr(prd, "get_engine", _should_not_run)

    assert prd.main([]) == 0


def test_digest_disabled_off_skips_without_touching_engine(monkeypatch) -> None:
    monkeypatch.setenv("SF_TELEGRAM_DIGEST_ENABLE", "OFF")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _should_not_run() -> None:
        raise AssertionError("get_engine must not be called when digest is disabled")

    monkeypatch.setattr(prd, "get_engine", _should_not_run)

    assert prd.main([]) == 0


def test_dry_run_builds_text(
    monkeypatch,
    deploy_tree,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SF_TELEGRAM_DIGEST_ENABLE", raising=False)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    pred = _sample_prediction()

    class _FakeRepo:
        def __init__(self, _session: object) -> None:
            pass

        def get_upcoming_predictions(self, **kwargs: object) -> list[Prediction]:
            return [pred]

    @contextmanager
    def _fake_session(engine: object | None = None):
        yield MagicMock()

    def _fake_extras(
        preds: list[Prediction],
        *,
        live_pinnacle: bool = True,
    ) -> dict[int, dict[str, object]]:
        assert len(preds) == 1
        return {
            1: {
                "edge_home": 0.05,
                "bet_decision_home": "lean_home",
                "live_odds_status": "ok",
            }
        }

    monkeypatch.setattr(prd, "get_engine", MagicMock())
    monkeypatch.setattr(prd, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(prd, "get_session", _fake_session)
    monkeypatch.setattr(prd, "PredictionRepository", _FakeRepo)
    monkeypatch.setattr(prd, "batch_live_response_extras", _fake_extras)

    code = prd.main(
        [
            "--dry-run",
            "--project-root",
            str(deploy_tree),
            "--no-live-pinnacle",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Home" in out and "Away" in out
    assert "smoke-run" in out


def test_send_path_missing_deploy_exits_before_db(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SF_TELEGRAM_DIGEST_ENABLE", raising=False)

    called: list[str] = []

    def _mark_engine() -> None:
        called.append("engine")

    monkeypatch.setattr(prd, "get_engine", _mark_engine)

    assert prd.main(["--project-root", str(tmp_path)]) == 1
    assert called == []


def test_disabled_allows_dry_run_with_db_mock(monkeypatch, deploy_tree, capsys) -> None:
    """При отключённом digest ``--dry-run`` всё ещё выполняет сценарий чтения."""
    monkeypatch.setenv("SF_TELEGRAM_DIGEST_ENABLE", "no")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    pred = _sample_prediction()

    class _FakeRepo:
        def __init__(self, _session: object) -> None:
            pass

        def get_upcoming_predictions(self, **kwargs: object) -> list[Prediction]:
            return [pred]

    @contextmanager
    def _fake_session(engine: object | None = None):
        yield MagicMock()

    monkeypatch.setattr(prd, "get_engine", MagicMock())
    monkeypatch.setattr(prd, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(prd, "get_session", _fake_session)
    monkeypatch.setattr(prd, "PredictionRepository", _FakeRepo)
    monkeypatch.setattr(
        prd,
        "batch_live_response_extras",
        lambda p, **k: {
            1: {"edge_home": None, "bet_decision_home": None, "live_odds_status": "disabled"}
        },
    )

    assert prd.main(["--dry-run", "--project-root", str(deploy_tree)]) == 0
    assert "Home" in capsys.readouterr().out


def test_dedup_marker_skips_telegram(monkeypatch, deploy_tree) -> None:
    """При SF_TELEGRAM_DIGEST_DEDUP и маркере Airflow задача возвращает 0 без sendMessage."""
    monkeypatch.delenv("SF_TELEGRAM_DIGEST_ENABLE", raising=False)
    monkeypatch.setenv("SF_TELEGRAM_DIGEST_DEDUP", "1")
    monkeypatch.setenv("AIRFLOW_CTX_DAG_RUN_ID", "manual__dedup-run")
    monkeypatch.setenv("AIRFLOW_CTX_TASK_ID", "post_refresh_digest")
    monkeypatch.setenv("BOT_TOKEN", "test-token-placeholder")
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", "999")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    marker = (
        deploy_tree
        / ".cache"
        / "digest_telegram_sent"
        / "manual__dedup-run_post_refresh_digest.lock"
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")

    pred = _sample_prediction()

    class _FakeRepo:
        def __init__(self, _session: object) -> None:
            pass

        def get_upcoming_predictions(self, **kwargs: object) -> list[Prediction]:
            return [pred]

    @contextmanager
    def _fake_session(engine: object | None = None):
        yield MagicMock()

    monkeypatch.setattr(prd, "get_engine", MagicMock())
    monkeypatch.setattr(prd, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(prd, "get_session", _fake_session)
    monkeypatch.setattr(prd, "PredictionRepository", _FakeRepo)
    monkeypatch.setattr(
        prd,
        "batch_live_response_extras",
        lambda p, **k: {
            1: {
                "edge_home": 0.02,
                "bet_decision_home": "neutral",
                "live_odds_status": "ok",
            }
        },
    )

    with patch.object(prd, "telegram_send_message") as mock_send:
        assert prd.main(["--project-root", str(deploy_tree), "--no-live-pinnacle"]) == 0
        mock_send.assert_not_called()
