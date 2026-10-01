"""Контрактные тесты типизации interim-данных."""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.data.clean import (
    _apply_dtype_conversion,
    _derive_status,
    _exclude_preseason_model_rows,
)


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


def test_nhl_preseason_is_removed_before_model_preparation_independent_of_score_and_status() -> (
    None
):
    """Тип сезона задаёт модельную границу и сохраняет regular/playoffs."""
    frame = pd.DataFrame(
        {
            "id": ["final-preseason", "off-preseason", "regular", "playoffs"],
            "game_type": ["preseason", "preseason", "regular", "playoffs"],
            "match_is_end": ["1", "0", "0", "1"],
            "home_points": ["", "3", "", "4"],
        }
    )

    result = _exclude_preseason_model_rows(frame, "nhl")

    assert result["id"].tolist() == ["regular", "playoffs"]
    assert frame["id"].tolist() == ["final-preseason", "off-preseason", "regular", "playoffs"]


def test_preseason_filter_does_not_change_other_tournaments() -> None:
    """Фильтр NHL не меняет модельные входы других турниров."""
    frame = pd.DataFrame({"id": ["one"], "game_type": ["preseason"]})

    result = _exclude_preseason_model_rows(frame, "other_tournament")

    assert result["id"].tolist() == ["one"]


def test_nhl_preseason_filter_requires_explicit_game_type() -> None:
    """Отсутствие сезонной метки не должно молча открывать модельный путь."""
    with pytest.raises(ValueError, match="game_type"):
        _exclude_preseason_model_rows(pd.DataFrame({"id": ["one"]}), "nhl")


@pytest.mark.parametrize("game_type", [None, "", "unknown", "1"])
def test_nhl_preseason_filter_rejects_missing_or_unknown_game_type(game_type: str | None) -> None:
    """Пустая или незнакомая метка не должна незаметно попасть в модельный вход."""
    frame = pd.DataFrame({"id": ["one"], "game_type": [game_type]})

    with pytest.raises(ValueError, match="game_type"):
        _exclude_preseason_model_rows(frame, "nhl")
