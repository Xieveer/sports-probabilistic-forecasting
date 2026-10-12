"""Один временной holdout матчей для long и wide моделей."""

from __future__ import annotations

import pandas as pd
import pytest

from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.training.train_eval_split import (
    TrainEvalSplitError,
    build_temporal_event_masks,
)


def test_same_events_in_long_and_wide_holdout() -> None:
    """Обе стороны одного матча и wide-строка получают одинаковый split."""
    wide = pd.DataFrame(
        {
            "id": ["a", "b", "c", "d"],
            "datetime": ["2025-06-30", "2025-07-01", "2026-06-30", "2026-07-01"],
        }
    )
    long = pd.concat([wide, wide], ignore_index=True)

    wide_train, wide_test = build_temporal_event_masks(wide, "2025-07-01/2026-06-30")
    long_train, long_test = build_temporal_event_masks(long, "2025-07-01/2026-06-30")

    assert wide.loc[wide_train, "id"].tolist() == ["a"]
    assert wide.loc[wide_test, "id"].tolist() == ["b", "c"]
    assert long.loc[long_train, "id"].tolist() == ["a", "a"]
    assert long.loc[long_test, "id"].tolist() == ["b", "c", "b", "c"]
    assert not (long_train & long_test).any()


def test_event_with_conflicting_times_is_rejected() -> None:
    """Один ID не может пересекать temporal boundary через разные строки."""
    frame = pd.DataFrame({"id": ["x", "x"], "datetime": ["2025-06-30", "2025-07-01"]})

    with pytest.raises(TrainEvalSplitError, match="разные времена"):
        build_temporal_event_masks(frame, "2025-07-01/2026-06-30")


def test_tscv_keeps_both_long_rows_in_same_fold() -> None:
    ids = pd.Series(["a", "a", "b", "b", "c", "c", "d", "d", "e", "e", "f", "f"])
    frame = pd.DataFrame({"feature": range(len(ids))})
    validator = TimeSeriesCrossValidator(n_splits=2)
    for train_idx, val_idx in validator.split(frame, groups=ids):
        train_ids = set(ids.iloc[train_idx])
        val_ids = set(ids.iloc[val_idx])
        assert train_ids.isdisjoint(val_ids)
        assert all((ids.iloc[train_idx] == event_id).sum() == 2 for event_id in train_ids)
        assert all((ids.iloc[val_idx] == event_id).sum() == 2 for event_id in val_ids)
