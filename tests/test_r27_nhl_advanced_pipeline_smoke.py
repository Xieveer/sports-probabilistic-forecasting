"""R27.10: smoke интеграции NHL + ``features=advanced`` без реальных parquet (CI).

Проверяет Hydra compose → ``materialize_features_config`` (inject sport EWM) →
``FeaturePipeline.generate_features`` на синтетическом wide, близком к NHL interim.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from hydra import compose, initialize_config_dir

from sports_forecast.features.pipeline import FeaturePipeline
from sports_forecast.features.rolling_contexts import materialize_features_config


def _synthetic_nhl_wide(n_matches: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(8)]
    rows: list[dict[str, object]] = []
    for i in range(n_matches):
        ht, at = teams[i % 8], teams[(i + 1) % 8]
        hp, ap = float(rng.integers(1, 6)), float(rng.integers(1, 6))
        rows.append(
            {
                "id": i + 1,
                "datetime": pd.Timestamp("2024-10-01", tz="UTC")
                + pd.Timedelta(days=i // 2, hours=19 + (i % 3)),
                "status": "finished",
                "home_team": ht,
                "away_team": at,
                "home_points": hp,
                "away_points": ap,
                "home_goals_reg": min(hp, ap),
                "away_goals_reg": min(hp, ap),
                "home_goals_full": hp,
                "away_goals_full": ap,
                "home_sog_ft": float(rng.integers(20, 40)),
                "away_sog_ft": float(rng.integers(20, 40)),
                "home_bs_ft": float(rng.integers(5, 15)),
                "away_bs_ft": float(rng.integers(5, 15)),
                "home_hits_ft": float(rng.integers(15, 35)),
                "away_hits_ft": float(rng.integers(15, 35)),
                "home_2pim_ft": float(rng.integers(4, 12)),
                "away_2pim_ft": float(rng.integers(4, 12)),
                "home_fow_ft": float(rng.integers(20, 35)),
                "away_fow_ft": float(rng.integers(20, 35)),
                "home_conference_standing": float(rng.integers(1, 16)),
                "away_conference_standing": float(rng.integers(1, 16)),
                "home_P": float(rng.integers(20, 80)),
                "away_P": float(rng.integers(20, 80)),
                "home_GP": float(rng.integers(10, 40)),
                "away_GP": float(rng.integers(10, 40)),
                "tour_num": float(i % 7),
                "tour_match_num": float(i % 82 + 1),
                "season": 20242025,
                "home_roster": (
                    '{"players": [{"positionCode": "C", "birthDate": "2000-01-01", '
                    '"sweaterNumber": 99}]}'
                ),
                "away_roster": '{"players": []}',
                "game_type": "regular",
                "match_end": "REG",
            }
        )
    return pd.DataFrame(rows)


def test_r27_advanced_nhl_pipeline_smoke() -> None:
    """Materialize + pipeline: sport EWM inject, inseason, порог числа f_-фичей (R27)."""
    conf_dir = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base=None, config_dir=str(conf_dir), job_name="pytest_r27"):
        cfg = compose(
            config_name="config",
            overrides=[
                "tournament=nhl",
                "market=winner_withOT",
                "market_spec=winner_withOT",
                "algorithm=dummy",
                "features=advanced",
            ],
        )
        fd = materialize_features_config(cfg.features, tournament_cfg=cfg.tournament)
        sport_keys = [k for k in fd["generators"] if k.startswith("ewm_sport_")]
        assert len(sport_keys) == 7
        assert fd["generators"]["ewm_sport_gf_diff"]["warmup"]["enabled"] is False

        pipe = FeaturePipeline(fd)
        wide = _synthetic_nhl_wide(60)
        long_df, feature_names = pipe.generate_features(wide, format="wide")

    assert len(long_df) == 120
    assert len(feature_names) >= 400
    inseason_cols = [c for c in feature_names if "inseason" in c and c.startswith("f_")]
    assert len(inseason_cols) > 0
    sport_inseason = [c for c in feature_names if "gf_diff" in c and "ewm" in c and "inseason" in c]
    assert len(sport_inseason) > 0
