"""Один временной holdout матчей для long и wide моделей."""

from __future__ import annotations

import pandas as pd
import pytest

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
