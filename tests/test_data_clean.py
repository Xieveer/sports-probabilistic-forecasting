"""Контрактные тесты типизации interim-данных."""

from __future__ import annotations

import pandas as pd
from omegaconf import OmegaConf

from sports_forecast.data.clean import _apply_dtype_conversion


def test_dtype_conversion_coerces_invalid_numeric_values_to_nullable_integer() -> None:
    """Числовая колонка приводится к Int64 без подстановки фиктивного счёта."""
    frame = pd.DataFrame({"score": ["2", "unknown"]})
    config = OmegaConf.create({"numeric": {"score": "int"}})

    result = _apply_dtype_conversion(frame, config, "test")

    assert str(result["score"].dtype) == "Int64"
    assert result["score"].tolist() == [2, pd.NA]
