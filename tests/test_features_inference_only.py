"""Контракт экономного сохранения признаков для публикации прогнозов."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
from omegaconf import OmegaConf
from pandas.testing import assert_frame_equal

from sports_forecast.features.features_build import process_tournament_new


def test_inference_only_keeps_predictions_and_skips_training_files(tmp_path: Path) -> None:
    """Refresh использует полную историю для фичей, но сохраняет только inference."""
    interim_root = tmp_path / "interim"
    input_dir = interim_root / "nhl"
    input_dir.mkdir(parents=True)
    pd.DataFrame({"id": [1, 2]}).to_parquet(input_dir / "matches_interim.parquet")
    generated = pd.DataFrame(
        {
            "id": [1, 1, 2, 2],
            "side": ["h", "a", "h", "a"],
            "status": ["finished", "finished", "upcoming", "upcoming"],
            "pl": ["A", "B", "C", "D"],
            "opp": ["B", "A", "D", "C"],
            "f_form": [0.1, 0.2, 0.3, 0.4],
        }
    )
    config = OmegaConf.create({"generators": []})
    with (
        patch(
            "sports_forecast.features.features_build.materialize_features_config", return_value={}
        ),
        patch("sports_forecast.features.features_build.FeaturePipeline") as pipeline,
        patch("sports_forecast.validation.gates.validate_processed"),
    ):
        pipeline.return_value.get_generator_summary.return_value = {}
        pipeline.return_value.generate_features.return_value = (generated, ["f_form"])
        process_tournament_new("nhl", interim_root, tmp_path / "normal", config)
        process_tournament_new(
            "nhl", interim_root, tmp_path / "refresh", config, inference_only=True
        )

    normal = tmp_path / "normal" / "nhl"
    refresh = tmp_path / "refresh" / "nhl"
    assert_frame_equal(
        pd.read_parquet(normal / "inference_long.parquet"),
        pd.read_parquet(refresh / "inference_long.parquet"),
    )
    assert_frame_equal(
        pd.read_parquet(normal / "inference_wide.parquet"),
        pd.read_parquet(refresh / "inference_wide.parquet"),
    )
    assert not (refresh / "train_long.parquet").exists()
    assert not (refresh / "train_wide.parquet").exists()
