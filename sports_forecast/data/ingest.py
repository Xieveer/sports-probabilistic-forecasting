from __future__ import annotations

from pathlib import Path

import pandas as pd

from sports_forecast.utils.logging import get_logger


logger = get_logger(__name__)


def process_tournament(source_dir: Path, raw_root: Path) -> None:
    """Обработать один турнир: JSON → Parquet (ингест данных)."""
    tournament_name = source_dir.name
    source_json = source_dir / "source.json"
    output_parquet = raw_root / tournament_name / "matches.parquet"

    if not source_json.exists():
        logger.warning("Пропускаю турнир %s: файл %s отсутствует", tournament_name, source_json)
        return

    logger.info("Турнир %s: читаю %s", tournament_name, source_json)
    df = pd.read_json(source_json, lines=False)

    logger.info("Турнир %s: загружено %d записей", tournament_name, len(df))

    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)

    logger.info("Турнир %s: parquet → %s", tournament_name, output_parquet)


def run() -> None:
    """Запуск полного процесса ingest: data/source → data/raw."""
    source_root = Path("data/source")
    raw_root = Path("data/raw")

    if not source_root.exists():
        raise FileNotFoundError(f"Каталог с источниками не найден: {source_root}")

    tournaments = sorted(p for p in source_root.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s не найдено ни одного турнира", source_root)
        return

    logger.info("Найдено турниров: %d", len(tournaments))

    for tournament_dir in tournaments:
        process_tournament(tournament_dir, raw_root)


if __name__ == "__main__":
    run()
