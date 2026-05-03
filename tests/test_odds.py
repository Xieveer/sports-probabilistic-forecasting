"""Тесты для sports_forecast.betting.odds — утилиты для работы с odds колонками."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from omegaconf import DictConfig, OmegaConf

from sports_forecast.betting.odds import (
    build_synthetic_odds_raw_series,
    extract_betting_odds,
    extract_odds_from_raw,
    find_odds_column,
    get_odds_column_long_format,
    get_odds_column_name,
)


# ─────────────────────────────────────────────────────────────────────────────
# Фикстуры
# ─────────────────────────────────────────────────────────────────────────────


def _make_market_spec(**kwargs) -> object:
    """Создать mock MarketSpec."""
    return OmegaConf.create(kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# get_odds_column_name
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOddsColumnName:
    """Тесты для get_odds_column_name."""

    def test_winner_home(self) -> None:
        spec = _make_market_spec(name="winner_home")
        assert get_odds_column_name(spec) == "odds_home_win"

    def test_winner_away(self) -> None:
        spec = _make_market_spec(name="winner_away")
        assert get_odds_column_name(spec) == "odds_away_win"

    def test_total_over_with_line(self) -> None:
        spec = _make_market_spec(name="total_over", line=6.5)
        assert get_odds_column_name(spec) == "odds_total_over_6.5"

    def test_total_under_with_line(self) -> None:
        spec = _make_market_spec(name="total_under", line=5.5)
        assert get_odds_column_name(spec) == "odds_total_under_5.5"

    def test_total_over_without_line(self) -> None:
        spec = _make_market_spec(name="total_over")
        assert get_odds_column_name(spec) is None

    def test_unknown_market(self) -> None:
        spec = _make_market_spec(name="exotic_market")
        assert get_odds_column_name(spec) is None

    def test_total_integer_line(self) -> None:
        spec = _make_market_spec(name="total_over", line=7)
        assert get_odds_column_name(spec) == "odds_total_over_7"

    def test_handicap_home(self) -> None:
        spec = _make_market_spec(name="handicap_home", line=-1.5)
        assert get_odds_column_name(spec) == "odds_handicap_home_-1.5"

    def test_handicap_away(self) -> None:
        spec = _make_market_spec(name="handicap_away", line=1.5)
        assert get_odds_column_name(spec) == "odds_handicap_away_1.5"


# ─────────────────────────────────────────────────────────────────────────────
# get_odds_column_long_format
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOddsColumnLongFormat:
    """Тесты для get_odds_column_long_format."""

    def test_winner_home_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "h") == "odds_home_win"

    def test_winner_away_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "a") == "odds_away_win"

    def test_winner_with_ot_home_side(self) -> None:
        spec = _make_market_spec(name="winner_withOT")
        assert get_odds_column_long_format(spec, "h") == "odds_home_win"

    def test_winner_with_ot_away_side(self) -> None:
        spec = _make_market_spec(name="winner_withOT")
        assert get_odds_column_long_format(spec, "a") == "odds_away_win"

    def test_winner_unknown_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "x") is None

    def test_total_over_long(self) -> None:
        spec = _make_market_spec(name="total_over", line=6.5)
        assert get_odds_column_long_format(spec, "h") == "odds_total_over_6.5"


# ─────────────────────────────────────────────────────────────────────────────
# find_odds_column
# ─────────────────────────────────────────────────────────────────────────────


class TestFindOddsColumn:
    """Тесты для find_odds_column."""

    def test_exact_match(self) -> None:
        df = pd.DataFrame({"odds_total_over_6.5": [2.0, 1.8], "other": [1, 2]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) == "odds_total_over_6.5"

    def test_not_found(self) -> None:
        df = pd.DataFrame({"other_col": [1, 2]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) is None

    def test_underscore_variant(self) -> None:
        df = pd.DataFrame({"odds_total_over_6_5": [2.0, 1.8]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) == "odds_total_over_6_5"

    def test_winner_home(self) -> None:
        df = pd.DataFrame({"odds_home_win": [1.5, 2.3], "home_points": [3, 4]})
        spec = _make_market_spec(name="winner_home")
        assert find_odds_column(df, spec) == "odds_home_win"

    def test_unknown_market_returns_none(self) -> None:
        df = pd.DataFrame({"some_col": [1]})
        spec = _make_market_spec(name="unknown_market")
        assert find_odds_column(df, spec) is None

    def test_missing_line_returns_none(self) -> None:
        df = pd.DataFrame({"odds_total_over_6.5": [2.0]})
        spec = _make_market_spec(name="total_over")
        assert find_odds_column(df, spec) is None

    @pytest.mark.parametrize(
        "line,expected_col",
        [
            (3.5, "odds_total_over_3.5"),
            (9.5, "odds_total_over_9.5"),
        ],
    )
    def test_parametrized_lines(self, line: float, expected_col: str) -> None:
        df = pd.DataFrame({expected_col: [2.0, 1.5]})
        spec = _make_market_spec(name="total_over", line=line)
        assert find_odds_column(df, spec) == expected_col


# ─────────────────────────────────────────────────────────────────────────────
# extract_odds_from_raw  (uses bookmaker config)
# ─────────────────────────────────────────────────────────────────────────────

_FONBET_CFG = OmegaConf.create(
    {
        "name": "fonbet",
        "market_keys": {
            "winner_home": "1",
            "winner_away": "2",
            "draw": "x",
            "total_over": "to_{line}",
            "total_under": "tu_{line}",
            "winner": "1",  # wide-format fallback (не используется напрямую)
        },
        "side_keys": {
            "h": "1",
            "a": "2",
        },
    }
)


class TestExtractOddsFromRaw:
    """Тесты для extract_odds_from_raw (bookmaker-driven)."""

    def test_winner_home(self) -> None:
        """Извлекает odds для winner_home по ключу '1'."""
        df = pd.DataFrame({"odds_raw": ["{'1': 1.48, '2': 2.45}"]})
        spec = _make_market_spec(name="winner_home", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(1.48)

    def test_winner_away(self) -> None:
        """Извлекает odds для winner_away по ключу '2'."""
        df = pd.DataFrame({"odds_raw": ["{'1': 1.48, '2': 2.45}"]})
        spec = _make_market_spec(name="winner_away", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(2.45)

    def test_total_over_with_line(self) -> None:
        """Извлекает odds для total_over, ключ = 'to_5.5'."""
        df = pd.DataFrame({"odds_raw": ["{'to_5.5': 1.90, 'tu_5.5': 1.85}"]})
        spec = _make_market_spec(name="total_over", data_format="wide", line=5.5)
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(1.90)

    def test_total_under_with_line(self) -> None:
        """Извлекает odds для total_under, ключ = 'tu_5.5'."""
        df = pd.DataFrame({"odds_raw": ["{'to_5.5': 1.90, 'tu_5.5': 1.85}"]})
        spec = _make_market_spec(name="total_under", data_format="wide", line=5.5)
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(1.85)

    def test_long_format_winner_h(self) -> None:
        """Long format winner: side='h' → ключ '1'."""
        df = pd.DataFrame(
            {
                "odds_raw": ["{'1': 1.60, '2': 2.30}", "{'1': 1.60, '2': 2.30}"],
                "side": ["h", "a"],
            }
        )
        spec = _make_market_spec(name="winner", data_format="long")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(1.60)  # home
        assert result.iloc[1] == pytest.approx(2.30)  # away

    def test_missing_odds_raw_column(self) -> None:
        """Если колонка odds_raw отсутствует — все NaN."""
        df = pd.DataFrame({"other": [1, 2]})
        spec = _make_market_spec(name="winner_home", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.isna().all()

    def test_nan_and_none_values(self) -> None:
        """NaN и None в odds_raw → NaN в результате."""
        df = pd.DataFrame({"odds_raw": [None, float("nan"), "nan"]})
        spec = _make_market_spec(name="winner_home", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.isna().all()

    def test_odds_below_1_excluded(self) -> None:
        """odds <= 1.0 исключаются."""
        df = pd.DataFrame({"odds_raw": ["{'1': 0.95, '2': 1.05}"]})
        spec = _make_market_spec(name="winner_home", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert np.isnan(result.iloc[0])

    def test_unknown_market_returns_nan(self) -> None:
        """Неизвестный market → все NaN."""
        df = pd.DataFrame({"odds_raw": ["{'1': 1.48}"]})
        spec = _make_market_spec(name="exotic_market", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.isna().all()

    def test_multiple_rows(self) -> None:
        """Корректная работа на нескольких строках."""
        df = pd.DataFrame(
            {
                "odds_raw": [
                    "{'1': 1.50, '2': 2.40}",
                    "{'1': 2.10, '2': 1.70}",
                    None,
                    "{'1': 1.80, '2': 1.95}",
                ]
            }
        )
        spec = _make_market_spec(name="winner_home", data_format="wide")
        result = extract_odds_from_raw(df, spec, _FONBET_CFG)
        assert result.iloc[0] == pytest.approx(1.50)
        assert result.iloc[1] == pytest.approx(2.10)
        assert np.isnan(result.iloc[2])
        assert result.iloc[3] == pytest.approx(1.80)


# ─────────────────────────────────────────────────────────────────────────────
# R26 — the_odds_api / winner_withOT / synthetic odds_raw
# ─────────────────────────────────────────────────────────────────────────────

_THE_ODDS_API_YAML = (
    Path(__file__).resolve().parents[1] / "conf" / "bookmaker" / "the_odds_api.yaml"
)
_THE_ODDS_API_FLAT: DictConfig = OmegaConf.load(_THE_ODDS_API_YAML)


class TestExtractOddsWinnerWithOT:
    """Long winner_withOT + side → те же ключи, что у winner (the_odds_api)."""

    def test_long_side_h_a(self) -> None:
        df = pd.DataFrame(
            {
                "odds_raw": ["{'1': 1.6, '2': 2.3}", "{'1': 1.6, '2': 2.3}"],
                "side": ["h", "a"],
            }
        )
        spec = _make_market_spec(name="winner_withOT", data_format="long")
        result = extract_odds_from_raw(df, spec, _THE_ODDS_API_FLAT)
        assert result.iloc[0] == pytest.approx(1.6)
        assert result.iloc[1] == pytest.approx(2.3)


class TestSyntheticOddsRawBuild:
    """Сборка odds_raw из pinnacle_* close (V3)."""

    def test_builds_dict_string(self) -> None:
        syn = _THE_ODDS_API_FLAT.synthetic_odds_raw
        df = pd.DataFrame(
            {
                "pinnacle_winner_withOT_home_close": [1.55],
                "pinnacle_winner_withOT_away_close": [2.45],
            }
        )
        s = build_synthetic_odds_raw_series(df, syn)
        parsed = extract_odds_from_raw(
            pd.DataFrame({"odds_raw": s, "side": ["h"]}),
            _make_market_spec(name="winner_withOT", data_format="long"),
            _THE_ODDS_API_FLAT,
        )
        assert parsed.iloc[0] == pytest.approx(1.55)

    def test_falls_back_to_legacy_v1_columns(self) -> None:
        syn = _THE_ODDS_API_FLAT.synthetic_odds_raw
        df = pd.DataFrame({"pinnacle_home_close": [1.9], "pinnacle_away_close": [1.95]})
        s = build_synthetic_odds_raw_series(df, syn)
        assert "1" in s.iloc[0] and "2" in s.iloc[0]


class TestExtractBettingOddsWideTransport:
    """Явный odds_transport.mode=wide_columns без odds_raw."""

    def test_long_winner_with_ot_wide_transport(self) -> None:
        transport = OmegaConf.create(
            {
                "mode": "wide_columns",
                "long_winner_specs": ["winner_withOT"],
                "home_close_column_candidates": ["pinnacle_winner_withOT_home_close"],
                "away_close_column_candidates": ["pinnacle_winner_withOT_away_close"],
            }
        )
        bm = OmegaConf.merge(_THE_ODDS_API_FLAT, OmegaConf.create({"odds_transport": transport}))
        df = pd.DataFrame(
            {
                "pinnacle_winner_withOT_home_close": [1.7, 1.7],
                "pinnacle_winner_withOT_away_close": [2.15, 2.15],
                "side": ["h", "a"],
            }
        )
        spec = _make_market_spec(name="winner_withOT", data_format="long")
        out = extract_betting_odds(df, spec, bm)
        assert out.iloc[0] == pytest.approx(1.7)
        assert out.iloc[1] == pytest.approx(2.15)
