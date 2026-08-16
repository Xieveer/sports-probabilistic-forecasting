"""Атомарная публикация готового provider source для canonical Worker."""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

from sports_forecast.orchestration.source_refresh import refresh_source_with_odds_result
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_REQUIRED_COLUMNS = frozenset({"id", "datetime", "match_is_end"})
_ODDS_COLUMNS = (
    "pinnacle_winner_withOT_home_close",
    "pinnacle_home_close",
    "onexbet_winner_home_close",
)


def publish_source_snapshot(source_csv: Path, current_csv: Path) -> Path:
    """Проверить и атомарно заменить scheduler-visible source snapshot.

    Args:
        source_csv: Полностью собранный временный source CSV provider/odds job.
        current_csv: Путь read-only snapshot, который читает canonical Worker.

    Returns:
        Путь опубликованного ``current_csv``.

    Raises:
        ValueError: Source не содержит обязательных колонок или пуст.
        OSError: Source недоступен либо snapshot не удалось опубликовать.
    """
    _validate_source_csv(source_csv)
    current_csv.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{current_csv.name}.", dir=current_csv.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(source_csv, temporary)
        temporary.replace(current_csv)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    logger.info("Опубликован source snapshot: %s", current_csv)
    return current_csv


def refresh_and_publish_source_snapshot(tournament: str, current_csv: Path) -> Path:
    """Получить provider source с mandatory odds и опубликовать его для Worker.

    Args:
        tournament: Идентификатор tournament/provider source.
        current_csv: Scheduler-visible immutable path для canonical Worker.

    Returns:
        Путь опубликованного ``current_csv``.

    Raises:
        SourceProviderError: Ошибка provider или обязательного odds post-step.
        ValueError: Собранный source не проходит минимальную проверку.
        OSError: Не удалось опубликовать snapshot.
    """
    source_csv, odds_result = refresh_source_with_odds_result(tournament)
    if odds_result is None or odds_result.quota_hit or not odds_result.merged_source:
        raise ValueError("Обязательный odds refresh не дал полного merged source")
    _validate_source_csv(source_csv, require_odds=True)
    return publish_source_snapshot(source_csv, current_csv)


def _validate_source_csv(source_csv: Path, *, require_odds: bool = False) -> None:
    """Проверить минимальный контракт source до замены current snapshot."""
    with source_csv.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = _REQUIRED_COLUMNS.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"source CSV не содержит обязательные колонки: {sorted(missing)}")
        rows = list(reader)
        if not rows:
            raise ValueError("source CSV не содержит событий")
        if not require_odds:
            return
        odds_column = next(
            (column for column in _ODDS_COLUMNS if column in reader.fieldnames), None
        )
        if odds_column is None:
            raise ValueError("source CSV не содержит обязательную колонку odds")
        missing_odds = [
            row["id"]
            for row in rows
            if not _is_finished(row["match_is_end"]) and not str(row.get(odds_column) or "").strip()
        ]
        if missing_odds:
            raise ValueError(
                "source CSV содержит будущие события без обязательных odds: "
                + ", ".join(missing_odds[:5])
            )


def _is_finished(value: str | None) -> bool:
    """Проверить признак завершённого матча в CSV provider source."""
    return str(value or "").strip().lower() in {"1", "true", "yes"}
