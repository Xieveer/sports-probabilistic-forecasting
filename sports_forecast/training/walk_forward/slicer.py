"""Incremental calendar slices for walk-forward evaluation."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class WalkForwardSlicer:
    """Yield ``(step_index, train_mask, test_mask)`` for expanding train / month OOS test.

    Calendar months use pandas period **M** on the datetime column. Naive datetimes are
    interpreted in a fixed calendar (treat as UTC wall-clock for boundaries).

    For each month *P* in chronological order among rows strictly after ``init_end``:
        - ``train_mask``: rows with ``ts <= init_end`` plus OOS rows strictly before month *P*.
        - ``test_mask``: OOS rows whose calendar month equals *P*.

    Empty ``test_mask`` slices are skipped. The last incomplete month is still included.

    Args:
        df: Frame aligned with features / target (same row order).
        datetime_col: Column with timestamps.
        frequency: Only ``\"month\"`` is supported.
        init_end: Inclusive end of the initial training period; rows with ``ts <= init_end``
            are part of the non-OOS core. Rows with ``ts > init_end`` enter walk-forward OOS.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        datetime_col: str,
        frequency: str,
        init_end: pd.Timestamp,
    ) -> None:
        if datetime_col not in df.columns:
            msg = f"datetime column {datetime_col!r} not in dataframe"
            raise KeyError(msg)
        if frequency != "month":
            msg = f"WalkForwardSlicer: unsupported frequency {frequency!r} (only 'month')"
            raise NotImplementedError(msg)
        self._init_end = pd.Timestamp(init_end)
        self._ts = pd.to_datetime(df[datetime_col], utc=False)
        if getattr(self._ts.dt, "tz", None) is not None:
            self._ts = self._ts.dt.tz_convert("UTC").dt.tz_localize(None)

    def __iter__(self) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
        ts = self._ts
        init_end = self._init_end

        oos_mask = ts > init_end
        if not bool(oos_mask.any()):
            logger.info("WalkForwardSlicer: no OOS rows after init_end — no steps")
            return

        oos_periods = ts.loc[oos_mask].dt.to_period("M")
        unique_periods: list[pd.Period] = sorted(oos_periods.unique(), key=lambda p: p.ordinal)

        step_index = 0
        for period in unique_periods:
            period_start = period.to_timestamp(how="start")
            test_mask_series = (ts.dt.to_period("M") == period) & oos_mask
            test_mask_arr = test_mask_series.to_numpy(dtype=bool)
            if not bool(test_mask_arr.any()):
                continue

            train_mask_series = (ts <= init_end) | (oos_mask & (ts < period_start))
            train_mask_arr = train_mask_series.to_numpy(dtype=bool)

            if train_mask_arr.sum() == 0:
                logger.warning(
                    "WalkForwardSlicer: step %s has empty train_mask — skipped",
                    period,
                )
                continue

            step_index += 1
            yield step_index, train_mask_arr, test_mask_arr

    def __len__(self) -> int:
        """Return the number of non-empty slices (materializes masks)."""
        return sum(1 for _ in self)
