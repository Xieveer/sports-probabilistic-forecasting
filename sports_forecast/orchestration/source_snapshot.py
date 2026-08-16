"""Атомарная публикация готового provider source для canonical Worker."""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

from sports_forecast.orchestration.source_refresh import refresh_source
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_REQUIRED_COLUMNS = frozenset({"id", "datetime", "match_is_end"})


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
    source_csv = refresh_source(tournament)
    return publish_source_snapshot(source_csv, current_csv)


def _validate_source_csv(source_csv: Path) -> None:
    """Проверить минимальный контракт source до замены current snapshot."""
    with source_csv.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = _REQUIRED_COLUMNS.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"source CSV не содержит обязательные колонки: {sorted(missing)}")
        if next(reader, None) is None:
            raise ValueError("source CSV не содержит событий")
