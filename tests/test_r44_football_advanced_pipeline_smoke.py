"""R44.10: smoke интеграции football_nationals + ``features=advanced`` (CI).

Проверяет Hydra compose → ``materialize_features_config`` (inject sport EWM, inseason)
→ ``FeaturePipeline.generate_features`` на синтетическом wide, близком к football interim.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from hydra import compose, initialize_config_dir

from sports_forecast.features.pipeline import FeaturePipeline
from sports_forecast.features.rolling_contexts import materialize_features_config


def _synthetic_football_wide(n_matches: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    teams = [f"NAT{i}" for i in range(12)]
    rows: list[dict[str, object]] = []
    for i in range(n_matches):
        ht, at = teams[i % 12], teams[(i + 3) % 12]
        hp, ap = float(rng.integers(0, 5)), float(rng.integers(0, 4))
        xg_h, xg_a = float(rng.uniform(0.5, 2.5)), float(rng.uniform(0.5, 2.5))
        rows.append(
            {
                "id": str(i + 1),
                "datetime": pd.Timestamp("2020-06-01", tz="UTC") + pd.Timedelta(days=7 * i),
                "status": "finished",
                "home_team": ht,
                "away_team": at,
                "home_points": hp,
                "away_points": ap,
                "home_goals_all": hp,
                "away_goals_all": ap,
                "home_xg_all": xg_h,
                "away_xg_all": xg_a,
                "home_corners_all": float(rng.integers(2, 12)),
                "away_corners_all": float(rng.integers(2, 12)),
                "home_possession_all": float(rng.integers(35, 65)),
                "away_possession_all": float(rng.integers(35, 65)),
                "home_shotstarget_all": float(rng.integers(2, 10)),
                "away_shotstarget_all": float(rng.integers(2, 10)),
                "match_importance": float(rng.choice([2, 3, 4])),
                "is_friendly": 0.0,
                "competition_code": "WC" if i % 5 == 0 else "FRII",
                "season_id": 20202021,
                "tour_num": float(i % 7),
                "weekday": float(i % 7),
            }
        )
    return pd.DataFrame(rows)


def test_r44_football_advanced_pipeline_smoke() -> None:
    """Materialize + pipeline: sport EWM inject, inseason via season_id, football spans [3,10]."""
    conf_dir = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base=None, config_dir=str(conf_dir), job_name="pytest_r44"):
        cfg = compose(
            config_name="config",
            overrides=[
                "tournament=football_nationals",
                "market=winner",
                "market_spec=winner_home",
                "algorithm=dummy",
                "features=advanced",
            ],
        )
        fd = materialize_features_config(cfg.features, tournament_cfg=cfg.tournament)
        sport_keys = [k for k in fd["generators"] if k.startswith("ewm_sport_")]
        assert len(sport_keys) == 10
        assert fd["generators"]["ewm_sport_goals_diff"]["spans"] == [3, 10]
        assert fd["generators"]["ewm_sport_goals_diff"]["warmup"]["enabled"] is False

        inseason_ctx = [
            c for c in fd["generators"]["ewm_diff"]["contexts"] if c["name"] == "inseason"
        ]
        assert len(inseason_ctx) == 1
        assert inseason_ctx[0]["keys"] == ["pl", "season_id"]

        pipe = FeaturePipeline(fd)
        wide = _synthetic_football_wide(40)
        long_df, feature_names = pipe.generate_features(wide, format="wide")

    assert len(long_df) == 80
    assert len(feature_names) >= 200
    inseason_cols = [c for c in feature_names if "inseason" in c and c.startswith("f_")]
    assert len(inseason_cols) > 0
    sport_xg = [c for c in feature_names if "xg_diff" in c and "ewm" in c and "inseason" in c]
    assert len(sport_xg) > 0
