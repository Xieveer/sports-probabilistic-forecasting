"""Контрактные тесты типизации interim-данных."""

from __future__ import annotations

import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.data.clean import _apply_dtype_conversion, _derive_status


def test_dtype_conversion_coerces_invalid_numeric_values_to_nullable_integer() -> None:
    """Числовая колонка приводится к Int64 без подстановки фиктивного счёта."""
    frame = pd.DataFrame({"score": ["2", "unknown"]})
    config = OmegaConf.create({"numeric": {"score": "int"}})

    result = _apply_dtype_conversion(frame, config, "test")

    assert str(result["score"].dtype) == "Int64"
    assert result["score"].tolist() == [2, pd.NA]


def test_status_treats_empty_canonical_scores_as_upcoming() -> None:
    """Empty string из canonical JSON не делает future event ложным live матчем."""
    frame = pd.DataFrame(
        {
            "match_is_end": ["0"],
            "home_points": [""],
            "away_points": [""],
        }
    )

    result = _derive_status(frame, ["home_points", "away_points"], "nhl")

    assert result["status"].tolist() == ["upcoming"]
