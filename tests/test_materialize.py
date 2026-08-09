"""Тесты для sports_forecast/materialize.py."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.materialize import (
    _aggregate_long_predictions,
    _resolve_model_provenance,
    materialize_predictions,
)


def _build_cfg() -> dict:
    return {
        "tournament": {"name": "uel_kz_1"},
        "market": {"name": "winner"},
        "market_spec": {"name": "winner", "data_format": "long"},
        "algorithm": {"name": "catboost"},
        "features": {"name": "basic"},
        "paths": {
            "models_dir": "models",
            "processed_dir": "data/processed",
            "predictions_dir": "data/predictions",
        },
    }


class TestMaterializePromotedContract:
    """Проверка прод-контракта materialize."""

    @patch("sports_forecast.materialize.load_model_from_path")
    @patch("sports_forecast.materialize.get_session")
    def test_uses_deploy_contract_for_prod(
        self,
        mock_get_session: MagicMock,
        mock_load_model: MagicMock,
        tmp_path: Path,
    ) -> None:
        cfg = OmegaConf.create(_build_cfg())

        promoted_dir = tmp_path / "models" / "uel_kz_1" / "winner" / "best"
        promoted_dir.mkdir(parents=True)
        (promoted_dir / "deploy.yaml").write_text(
            "model:\n  algorithm: lgbm\n  featureset: advanced\n",
            encoding="utf-8",
        )
        (promoted_dir / "model_prod.lgbm").touch()
        (promoted_dir / "features.txt").write_text("f_a\nf_b", encoding="utf-8")
        algorithm_cfg_dir = tmp_path / "conf" / "algorithm"
        algorithm_cfg_dir.mkdir(parents=True)
        (algorithm_cfg_dir / "lgbm.yaml").write_text(
            "name: lgbm\n_target_: sports_forecast.training.models.lgbm.LGBMModel\n",
            encoding="utf-8",
        )

        processed_dir = tmp_path / "data" / "processed" / "uel_kz_1"
        processed_dir.mkdir(parents=True)
        inference_df = pd.DataFrame(
            {
                "id": ["m1", "m1"],
                "side": ["h", "a"],
                "datetime": ["2026-01-01T12:00:00", "2026-01-01T12:00:00"],
                "pl_short_name_en": ["Home", "Away"],
                "f_a": [1.0, 2.0],
                "f_b": [3.0, 4.0],
                "odds_raw": [None, None],
            }
        )
        inference_df.to_parquet(processed_dir / "inference_long.parquet", index=False)

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.2, 0.8], [0.6, 0.4]])
        mock_load_model.return_value = mock_model

        mock_repo = MagicMock()
        with_session = nullcontext(MagicMock())
        mock_get_session.return_value = with_session

        with (
            patch("sports_forecast.materialize.PredictionRepository", return_value=mock_repo),
            patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path),
        ):
            ok = materialize_predictions(cfg, version="prod")

        assert ok is True
        assert mock_load_model.call_args is not None
        algorithm_cfg = mock_load_model.call_args.args[0]
        assert str(algorithm_cfg.name) == "lgbm"

        assert mock_repo.publish_showcase.call_count == 1
        records = mock_repo.publish_showcase.call_args.args[0]
        assert len(records) == 1
        assert records[0]["algorithm"] == "lgbm"
        assert records[0]["featureset"] == "advanced"
        assert records[0]["model_version"] == "lgbm_advanced_prod"

    def test_prod_fails_without_deploy_contract(self, tmp_path: Path) -> None:
        cfg = OmegaConf.create(_build_cfg())

        with patch("sports_forecast.materialize.PROJECT_ROOT", tmp_path):
            ok = materialize_predictions(cfg, version="prod")

        assert ok is False


def test_aggregate_long_uses_pl_when_pl_short_name_en_absent() -> None:
    """NHL long inference: идентификатор в ``pl``, без ``pl_short_name_en``."""
    df = pd.DataFrame(
        {
            "id": ["m1", "m1"],
            "side": ["h", "a"],
            "datetime": ["2026-05-14T00:00:00Z", "2026-05-14T00:00:00Z"],
            "pl": ["TOR", "OTT"],
            "f_x": [1.0, 2.0],
        }
    )
    proba = np.array([[0.3, 0.7], [0.55, 0.45]])
    out = _aggregate_long_predictions(df, proba)
    assert len(out) == 1
    assert out.iloc[0]["home_player"] == "TOR"
    assert out.iloc[0]["away_player"] == "OTT"


def test_aggregate_long_prefers_pl_short_name_en_over_pl() -> None:
    """Если задано короткое имя игрока, оно важнее аббревиатуры ``pl``."""
    df = pd.DataFrame(
        {
            "id": ["m1", "m1"],
            "side": ["h", "a"],
            "datetime": ["2026-01-01T12:00:00", "2026-01-01T12:00:00"],
            "pl": ["H_CODE", "A_CODE"],
            "pl_short_name_en": ["Home Star", "Away Star"],
            "f_a": [1.0, 2.0],
        }
    )
    proba = np.array([[0.2, 0.8], [0.6, 0.4]])
    out = _aggregate_long_predictions(df, proba)
    assert out.iloc[0]["home_player"] == "Home Star"
    assert out.iloc[0]["away_player"] == "Away Star"


def test_resolve_model_provenance_uses_active_pointer_for_explicit_pool() -> None:
    """Pool materialize получает immutable identity только из active registry pointer."""
    cfg = OmegaConf.create(
        {
            "model_pool": {"name": "football_nationals_winner"},
            "market_spec": {"name": "winner"},
        }
    )
    registry = MagicMock()
    registry.get_active.return_value = MagicMock(
        model_identity="pool:football_nationals_winner:winner:immutable"
    )

    provenance = _resolve_model_provenance(cfg, registry)

    assert provenance == (
        "football_nationals_winner",
        "pool:football_nationals_winner:winner:immutable",
    )
