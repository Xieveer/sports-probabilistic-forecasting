"""Регрессия: после сортировки по времени таргет остаётся выровненным по строкам df."""

from __future__ import annotations

import pandas as pd


def test_sort_aligns_target_with_rows_not_iloc_range() -> None:
    """Старый паттерн ``target.iloc[df.index]`` после ``reset_index`` даёт неверный порядок.

    ``iloc[0:n]`` — это первые n меток исходного target, а не target для отсортированных строк.
    """
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"]),
            "pl_goals_full": [0.0, 2.0, 1.0],
            "opp_goals_full": [1.0, 1.0, 3.0],
        }
    )
    target = (df["pl_goals_full"] > df["opp_goals_full"]).astype(int)

    # Неверно (как было в trainer до фикса):
    df_bug = df.sort_values("datetime").reset_index(drop=True)
    wrong = target.iloc[df_bug.index].reset_index(drop=True)
    # Верно:
    order = df.sort_values("datetime").index
    df_ok = df.loc[order].reset_index(drop=True)
    right = target.loc[order].reset_index(drop=True)

    expected = (df_ok["pl_goals_full"] > df_ok["opp_goals_full"]).astype(int)
    pd.testing.assert_series_equal(right, expected, check_names=False)
    assert not wrong.equals(expected), "регрессия: wrong alignment должен отличаться от goals"
