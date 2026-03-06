"""CLI-скрипт для ручного запуска валидации данных по всем слоям.

Usage::

    uv run python -m sports_forecast.validation.run_validation
    # или
    make validate-data
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from sports_forecast.validation.gates import (
    validate_interim,
    validate_processed,
    validate_raw,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """Запустить валидацию всех данных по слоям.

    Returns:
        0 если всё ок, 1 если есть ошибки.
    """
    all_ok = True
    total = 0
    failed = 0

    raw_root = PROJECT_ROOT / "data" / "raw"
    interim_root = PROJECT_ROOT / "data" / "interim"
    processed_root = PROJECT_ROOT / "data" / "processed"

    # ── RAW ───────────────────────────────────────────────────────
    if raw_root.exists():
        for d in sorted(raw_root.iterdir()):
            p = d / "matches.parquet"
            if p.exists():
                total += 1
                r = validate_raw(pd.read_parquet(p), tournament=d.name, raise_on_error=False)
                if not r.is_valid:
                    all_ok = False
                    failed += 1

    # ── INTERIM ───────────────────────────────────────────────────
    if interim_root.exists():
        for d in sorted(interim_root.iterdir()):
            p = d / "matches_interim.parquet"
            if p.exists():
                total += 1
                r = validate_interim(pd.read_parquet(p), tournament=d.name, raise_on_error=False)
                if not r.is_valid:
                    all_ok = False
                    failed += 1

    # ── PROCESSED ─────────────────────────────────────────────────
    if processed_root.exists():
        for d in sorted(processed_root.iterdir()):
            for fmt in ("train_long", "train_wide"):
                p = d / f"{fmt}.parquet"
                if p.exists():
                    total += 1
                    data_format = "long" if "long" in fmt else "wide"
                    r = validate_processed(
                        pd.read_parquet(p),
                        data_format=data_format,
                        tournament=d.name,
                        raise_on_error=False,
                    )
                    if not r.is_valid:
                        all_ok = False
                        failed += 1

    # ── Summary ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    if all_ok:
        print(f"✅ Валидация завершена: {total} проверок, все OK")
    else:
        print(f"❌ Валидация завершена: {failed}/{total} проверок FAILED")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
