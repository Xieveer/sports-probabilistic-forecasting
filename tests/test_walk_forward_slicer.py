"""Unit tests for :class:`WalkForwardSlicer`."""

from __future__ import annotations

import pandas as pd
import pytest

from sports_forecast.training.walk_forward.slicer import WalkForwardSlicer


def test_slicer_empty_dataframe_yields_nothing() -> None:
    df = pd.DataFrame({"dt": pd.Series(dtype="datetime64[ns]"), "x": pd.Series(dtype=float)})
    with pytest.raises(KeyError):
        list(WalkForwardSlicer(df, "datetime", "month", pd.Timestamp("2024-06-01")))


def test_slicer_no_oos_yields_nothing() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-05", "2024-02-10"]),
            "x": [1, 2],
        }
    )
    init_end = pd.Timestamp("2024-12-31")
    steps = list(WalkForwardSlicer(df, "datetime", "month", init_end))
    assert steps == []


def test_slicer_skips_empty_test_month() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-03-15"]),
            "x": [1, 2],
        }
    )
    init_end = pd.Timestamp("2024-01-15")
    slicer = WalkForwardSlicer(df, "datetime", "month", init_end)
    steps = list(slicer)
    assert len(steps) == 1
    _, train_m, test_m = steps[0]
    assert train_m.sum() == 1
    assert test_m.sum() == 1


def test_slicer_year_boundary_naive_utc_semantics() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2023-11-15",
                    "2023-12-20",
                    "2024-01-10",
                    "2024-02-05",
                ]
            ),
            "x": [10, 20, 30, 40],
        }
    )
    init_end = pd.Timestamp("2023-12-31 23:59:59")
    steps = list(WalkForwardSlicer(df, "datetime", "month", init_end))
    assert len(steps) == 2
    assert steps[0][0] == 1
    assert steps[1][0] == 2
    _, tr1, te1 = steps[0]
    _, tr2, te2 = steps[1]
    assert te1.sum() == 1 and int(df.loc[te1, "x"].iloc[0]) == 30
    assert tr2.sum() >= tr1.sum()


def test_slicer_includes_partial_last_month() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-02-28"]),
            "x": [1, 2, 3],
        }
    )
    init_end = pd.Timestamp("2024-01-31")
    steps = list(WalkForwardSlicer(df, "datetime", "month", init_end))
    months = [df.loc[s[2], "datetime"].dt.month.iloc[0] for s in steps]
    assert months == [2]


def test_unsupported_frequency() -> None:
    df = pd.DataFrame({"datetime": pd.to_datetime(["2024-01-01"]), "x": [1]})
    with pytest.raises(NotImplementedError):
        list(WalkForwardSlicer(df, "datetime", "week", pd.Timestamp("2023-01-01")))


def test_len_counts_non_empty_slices() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
            "x": [1, 2, 3],
        }
    )
    init_end = pd.Timestamp("2024-01-15")
    s = WalkForwardSlicer(df, "datetime", "month", init_end)
    assert len(s) == 2
