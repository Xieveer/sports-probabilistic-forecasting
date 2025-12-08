"""Модуль очистки и предобработки данных матчей.

Этот модуль отвечает за преобразование сырых данных (raw) в очищенный формат (interim).

Основные функции:

* Чтение parquet файлов с данными матчей
* Базовая валидация и очистка данных
* Сохранение обработанных данных

Структура данных:

* Входные данные: data/raw/{tournament_name}/matches.parquet
* Выходные данные: data/interim/{tournament_name}/matches_clean.parquet

Attributes:
    PROJECT_ROOT (Path): Корневая директория проекта
    DATA_RAW_DIR (Path): Директория с сырыми данными
    DATA_PROCESSED_DIR (Path): Директория для обработанных данных
    logger (Logger): Логгер модуля

Example:
    Запуск обработки всех турниров::

        $ python -m sports_forecast.features.clean

    Или через DVC::

        $ dvc repro features
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sports_forecast.utils.logging import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Директория с сырыми данными матчей
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

#: Директория для обработанных данных
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "interim"

#: Логгер модуля для отслеживания процесса обработки
logger = get_logger(__name__)


def process_tournament(tournament_dir: Path) -> None:
    """Обработать один турнир: raw → interim.

    Читает сырые данные матчей из parquet-файла, выполняет базовую очистку
    и сохраняет результат в interim директорию.

    Args:
        tournament_dir: Путь к директории турнира в data/raw.
            Ожидается структура: tournament_dir/matches.parquet

    Returns:
        None

    Raises:
        FileNotFoundError: Если файл matches.parquet не найден (логируется warning).

    Examples:
        >>> from pathlib import Path
        >>> tournament_path = Path("data/raw/premier_league_2023")
        >>> process_tournament(tournament_path)

    Note:
        В будущем планируется добавить:
        - Выбор необходимых колонок
        - Приведение типов данных
        - Фильтрацию по статусу матча
        - Обработку пропущенных значений

    Todo:
        * Добавить валидацию схемы данных
        * Реализовать обработку ошибок парсинга
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
        "Турнир %s: записываю interim (%d записей) → %s",
        tournament_name,
        len(df_clean),
        out_path,
    )
    df_clean.to_parquet(out_path, index=False)


def run_features_pipeline() -> None:
    """Запустить обработку всех турниров из data/raw.

    Сканирует директорию data/raw на наличие поддиректорий с турнирами
    и последовательно обрабатывает каждый турнир через process_tournament().

    Returns:
        None

    Raises:
        RuntimeError: Если директория data/raw не существует.

    Examples:
        Запуск из командной строки::

            >>> run_features_pipeline()
            INFO: Найдено турниров: 5
            INFO: Турнир premier_league_2023: читаю raw ...

        Или через Python API::

            >>> from sports_forecast.features.clean import run_features_pipeline
            >>> run_features_pipeline()

    See Also:
        process_tournament: Обработка отдельного турнира

    Note:
        Функция автоматически создает необходимые директории для выходных данных.
    """
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
