from __future__ import annotations

from pathlib import Path

import pandas as pd

from sports_forecast.utils.logging import get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

logger = get_logger(__name__)


def process_tournament(tournament_dir: Path) -> None:
    """Обработать один турнир: raw → processed.

    Пока это: прочитать raw parquet и сохранить почти как есть.
    Позже сюда добавим:
    - выбор колонок;
    - приведение типов;
    - фильтрацию по статусу матча и т.п.
    """
    tournament_name = tournament_dir.name
    raw_path = tournament_dir / "matches.parquet"

    if not raw_path.exists():
        logger.warning("Турнир %s: файл %s не найден, пропускаю", tournament_name, raw_path)
        return

    logger.info("Турнир %s: читаю raw %s", tournament_name, raw_path)
    df: pd.DataFrame = pd.read_parquet(raw_path)

    if df is None or df.empty:
        logger.warning("Турнир %s: пустой датафрейм, пропускаю", tournament_name)
        return

    df_clean: pd.DataFrame = df.copy()

    out_dir = DATA_PROCESSED_DIR / tournament_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matches_clean.parquet"

    logger.info(
        "Турнир %s: записываю processed (%d записей) → %s",
        tournament_name,
        len(df_clean),
        out_path,
    )
    df_clean.to_parquet(out_path, index=False)


def run_features_pipeline() -> None:
    """Запустить обработку всех турниров из data/raw."""
    if not DATA_RAW_DIR.exists():
        raise RuntimeError(f"Папка с raw-данными не найдена: {DATA_RAW_DIR}")

    tournaments = sorted(p for p in DATA_RAW_DIR.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s нет ни одного турнира, ничего обрабатывать", DATA_RAW_DIR)
        return

    logger.info("Найдено турниров: %d", len(tournaments))
    for tournament_dir in tournaments:
        process_tournament(tournament_dir)


if __name__ == "__main__":
    run_features_pipeline()
