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
    check_schema_drift,
    report_duplicate_ids,
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
    drift_detected = 0
    duplicate_reports: list[dict[str, object]] = []

    raw_root = PROJECT_ROOT / "data" / "raw"
    interim_root = PROJECT_ROOT / "data" / "interim"
    processed_root = PROJECT_ROOT / "data" / "processed"
    snapshot_dir = PROJECT_ROOT / "data" / ".schema_snapshots"

    # ── RAW ───────────────────────────────────────────────────────
    if raw_root.exists():
        for d in sorted(raw_root.iterdir()):
            p = d / "matches.parquet"
            if p.exists():
                total += 1
                df = pd.read_parquet(p)
                r = validate_raw(df, tournament=d.name, raise_on_error=False)
                if not r.is_valid:
                    all_ok = False
                    failed += 1
                # Schema drift
                drift = check_schema_drift(df, "raw", d.name, snapshot_dir)
                if drift.has_drift:
                    drift_detected += 1
                # Duplicate IDs
                dup = report_duplicate_ids(df, "raw", d.name)
                if dup.get("duplicated_rows", 0) > 0:
                    duplicate_reports.append(dup)

    # ── INTERIM ───────────────────────────────────────────────────
    if interim_root.exists():
        for d in sorted(interim_root.iterdir()):
            p = d / "matches_interim.parquet"
            if p.exists():
                total += 1
                df = pd.read_parquet(p)
                r = validate_interim(df, tournament=d.name, raise_on_error=False)
                if not r.is_valid:
                    all_ok = False
                    failed += 1
                # Schema drift
                drift = check_schema_drift(df, "interim", d.name, snapshot_dir)
                if drift.has_drift:
                    drift_detected += 1
                # Duplicate IDs
                dup = report_duplicate_ids(df, "interim", d.name)
                if dup.get("duplicated_rows", 0) > 0:
                    duplicate_reports.append(dup)

    # ── PROCESSED ─────────────────────────────────────────────────
    if processed_root.exists():
        for d in sorted(processed_root.iterdir()):
            for fmt in ("train_long", "train_wide"):
                p = d / f"{fmt}.parquet"
                if p.exists():
                    total += 1
                    df = pd.read_parquet(p)
                    data_format = "long" if "long" in fmt else "wide"
                    r = validate_processed(
                        df,
                        data_format=data_format,
                        tournament=d.name,
                        raise_on_error=False,
                    )
                    if not r.is_valid:
                        all_ok = False
                        failed += 1
                    # Schema drift
                    drift = check_schema_drift(df, f"processed_{data_format}", d.name, snapshot_dir)
                    if drift.has_drift:
                        drift_detected += 1

    # ── Summary ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    if all_ok:
        print(f"✅ Валидация завершена: {total} проверок, все OK")
    else:
        print(f"❌ Валидация завершена: {failed}/{total} проверок FAILED")

    if drift_detected:
        print(f"⚠️  Schema drift: {drift_detected} файлов изменили структуру")
    else:
        print("✅ Schema drift: нет изменений")

    if duplicate_reports:
        print(f"⚠️  Дубли ID: {len(duplicate_reports)} датасетов с дублями:")
        for dup in duplicate_reports:
            print(
                f"   {dup['stage']}/{dup['tournament']}: "
                f"{dup['duplicated_rows']} строк, {dup['duplicated_ids']} уник. ID"
            )
    else:
        print("✅ Дубли ID: нет дублей")

    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
