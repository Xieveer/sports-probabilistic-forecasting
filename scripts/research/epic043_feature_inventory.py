"""Инвентаризация всех входных признаков футбольной wide-модели."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import pandas as pd


def main() -> None:
    """Записать пропуски, уникальность и точные дубликаты колонок."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    names = args.features.read_text(encoding="utf-8").splitlines()
    frame = pd.read_parquet(args.processed, columns=["datetime", *names])
    frame = frame.loc[cast(Any, pd.to_datetime(frame.datetime, utc=True)).lt("2025-07-01"), names]
    candidates: dict[tuple[int, int], list[str]] = defaultdict(list)
    rows = []
    for name in names:
        values = frame[name]
        hashed: Any = pd.util.hash_pandas_object(values, index=False).to_numpy(dtype="uint64")
        key = (int(hashed.sum(dtype="uint64")), int((hashed ^ (hashed >> 32)).sum(dtype="uint64")))
        duplicate_of = next(
            (previous for previous in candidates[key] if values.equals(frame[previous])), None
        )
        if duplicate_of is None:
            candidates[key].append(name)
        rows.append(
            {
                "feature": name,
                "missing_fraction": float(values.isna().mean()),
                "unique_non_null": int(values.nunique(dropna=True)),
                "duplicate_of": duplicate_of,
            }
        )
    result = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(
        f"features={len(result)} constants={(result.unique_non_null <= 1).sum()} "
        f"duplicates={result.duplicate_of.notna().sum()}"
    )


if __name__ == "__main__":
    main()
